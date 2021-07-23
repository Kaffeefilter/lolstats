import configparser
import requests
import json
from ratelimit import limits, sleep_and_retry, RateLimitException
from backoff import on_exception, expo
from progress.bar import Bar
from pprint import pprint
import pymongo

def dataNotFound(e):
    return 404 == e.response.status_code

#ratelimit imposed by Riot
#20 requests every 1 seconds(s)
#100 requests every 2 minutes(s)
#do one less just to be sure
@on_exception(expo, Exception, max_tries=8, giveup=dataNotFound)
@sleep_and_retry
@limits(calls=19, period=1)
@sleep_and_retry
@limits(calls=99, period=120)
def call_riot(url, apikey):
    response = requests.get(url, headers={"X-Riot-Token": apikey})

    if response.status_code >= 500:
        raise Exception(f'API response: {response.status_code}')
    return response

def generateRunesLookup():
    runes = requests.get("http://ddragon.leagueoflegends.com/cdn/11.11.1/data/en_US/runesReforged.json")
    if runes.ok:
        runes = json.loads(runes.text)
        lookup = {}
        for idx, tree in enumerate(runes):
            for jdx, slot in enumerate(tree["slots"]):
                for kdx, rune in enumerate(slot["runes"]):
                    lookup[rune["id"]] = str(idx) + str(jdx) + str(kdx)
    else:
        print("ddragon not reachable")
    
    #print(json.dumps(lookup, indent=4))
    return lookup

#didn't find shard infos so hardcoding it in for now
#using items.json as example
#FlatAbilityHasteMod is a guess since there is no data for it in items.json
#FlatHPPoolModMax, AdaptiveForce and FlatAdaptiveForceMod are also made up
def generateShardLookup():
    lookup = {
        "5001": {
            "rawDescription": "perk_tooltip_StatModHealthScaling",
            "tags": [
                "Health",
                "Scaling"
            ],
            "stats": {
                "FlatHPPoolMod": 15,
                "FlatHPPoolModMax": 90
            }
        },
        "5002": {
            "rawDescription": "perk_tooltip_StatModArmor",
            "tags": [
                "Armor"
            ],
            "stats": {
                "FlatArmorMod": 6
            }
        },
        "5003": {
            "rawDescription": "perk_tooltip_StatModMagicResist",
            "tags": [
                "SpellBlock"
            ],
            "stats": {
                "FlatSpellBlockMod": 8
            }
        },
        "5005": {
            "rawDescription": "perk_tooltip_StatModAttackSpeed",
            "tags": [
                "AttackSpeed"
            ],
            "stats": {
                "PercentAttackSpeedMod": 10
            }
        },
        "5007": {
            "rawDescription": "perk_tooltip_StatModCooldownReductionScaling",
            "tags": [
                "AbilityHaste"
            ],
            "stats": {
                "FlatAbilityHasteMod": 8
            }
        },
        "5008": {
            "rawDescription": "perk_tooltip_StatModAdaptive",
            "tags": [
                "AdaptiveForce"
            ],
            "stats": {
                "FlatAdaptiveForceMod": 9
            }
        }
    }

    return lookup


def getNGames(n):
    summonername = "pwain"
    region = "euw1"
    regionv5 = "europe"

    config = configparser.ConfigParser()
    config.read("apikey.ini")
    apikey = config["riotapi"]["apiKey"]

    summoner = call_riot("https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-name/" + summonername, apikey)
    me = json.loads(summoner.text)

    #runeslookup = generateRunesLookup()
    #shardslookup = generateShardLookup()

    #get a list of the last n matches played
    matches = []
    indexes = list(range(0, n, 100))
    indexes.append(n)
    prevIndex = -1
    for index in indexes:
        if prevIndex >= 0:
            r = call_riot(f"https://{regionv5}.api.riotgames.com/lol/match/v5/matches/by-puuid/{me['puuid']}/ids?start={prevIndex}&count={index - prevIndex}", apikey)
            matches.extend(json.loads(r.text))
        prevIndex = index

    #get list of ids of relevant gamemodes
    r = requests.get("https://static.developer.riotgames.com/docs/lol/queues.json")
    queues = json.loads(r.text)
    gamefilter = [ queue["queueId"] for queue in queues if queue["notes"] == None if queue["description"] != None if "5v5" in queue["description"] or "Clash" in queue["description"] ]

    bar = Bar('Processing', max=n)
    db = []
    for match in matches:
        #get match details
        r = call_riot(f"https://{regionv5}.api.riotgames.com/lol/match/v5/matches/{match}", apikey)
        if not r.ok:
            bar.next()
            continue
        matchdetails = json.loads(r.text)
        if matchdetails["info"]["queueId"] not in gamefilter:
            bar.next()
            continue     

        #get match timeline for summonersrift games (not aram)
        if matchdetails["info"]["gameMode"] == "CLASSIC":
            r = call_riot(f"https://{regionv5}.api.riotgames.com/lol/match/v5/matches/{match}/timeline", apikey)
            matchTimeline = json.loads(r.text)

        #get the right stats
        for participant in matchdetails["info"]["participants"]:
            if participant["summonerName"] == summonername:
                summonerMatchStats = participant

        teamKills = 0
        teammates = []
        opponents = []
        for participant in matchdetails["info"]["participants"]:
            #get opponents stats
            if (
                participant["teamId"] != summonerMatchStats["teamId"] and 
                participant["individualPosition"] == summonerMatchStats["individualPosition"]
            ):
                opponentMatchStats = participant

            #calculate team kills since there is no data for it
            if participant["teamId"] == summonerMatchStats["teamId"]:
                teamKills += participant["kills"]

            #get teammates and opponents
            if participant["summonerName"] == summonername: continue
            elif participant["teamId"] == summonerMatchStats["teamId"]:
                teammates.append({"puuid": participant["puuid"], "name": participant["summonerName"]})
            else: 
                opponents.append({"puuid": participant["puuid"], "name": participant["summonerName"]})

        #get timelinestats
        summonerTimeline = []
        opponentTimeline = []
        if matchdetails["info"]["gameMode"] == "CLASSIC":

            #get timeline id for summoner and opponent
            for participant in matchTimeline["info"]["participants"]:
                if participant["puuid"] == summonerMatchStats["puuid"]:
                    summonerTimelineId = participant["participantId"]
                if participant["puuid"] == opponentMatchStats["puuid"]:
                    opponentTimelineId = participant["participantId"]

            for frame in matchTimeline["info"]["frames"]:
                summonerTimeline.append({
                    "cs": frame["participantFrames"][str(summonerTimelineId)]["minionsKilled"] + frame["participantFrames"][str(summonerTimelineId)]["jungleMinionsKilled"],
                    "currentGold": frame["participantFrames"][str(summonerTimelineId)]["currentGold"],
                    "totalGold": frame["participantFrames"][str(summonerTimelineId)]["totalGold"],
                    "xp": frame["participantFrames"][str(summonerTimelineId)]["xp"]
                })
                opponentTimeline.append({
                    "cs": frame["participantFrames"][str(opponentTimelineId)]["minionsKilled"] + frame["participantFrames"][str(opponentTimelineId)]["jungleMinionsKilled"],
                    "currentGold": frame["participantFrames"][str(opponentTimelineId)]["currentGold"],
                    "totalGold": frame["participantFrames"][str(opponentTimelineId)]["totalGold"],
                    "xp": frame["participantFrames"][str(opponentTimelineId)]["xp"]
                })

        dbentry = {
            "game": {
                "championId": summonerMatchStats["championId"],
                "championName": summonerMatchStats["championName"],
                "teamId": summonerMatchStats["teamId"],
                "queueId": matchdetails["info"]["queueId"],
                "gameMode": matchdetails["info"]["gameMode"],
                "matchId": matchdetails["metadata"]["matchId"],
                "win": summonerMatchStats["win"],
                "gameDuration": matchdetails["info"]["gameDuration"],
                "individualPosition": summonerMatchStats["individualPosition"] if matchdetails["info"]["gameMode"] != "ARAM" else "ARAM",
                "lane": summonerMatchStats["lane"] if matchdetails["info"]["gameMode"] != "ARAM" else "MIDDLE"
            },
            "stats": {
                "kda": {
                    "kills": summonerMatchStats["kills"],
                    "deaths": summonerMatchStats["deaths"],
                    "assists": summonerMatchStats["assists"],
                    "double": summonerMatchStats["doubleKills"],
                    "triple": summonerMatchStats["tripleKills"],
                    "quadra": summonerMatchStats["quadraKills"],
                    "penta": summonerMatchStats["pentaKills"],
                    "unreal": summonerMatchStats["unrealKills"],
                    "teamKills": teamKills
                },
                "damage": {
                    "total": summonerMatchStats["totalDamageDealtToChampions"],
                    "magic": summonerMatchStats["magicDamageDealtToChampions"],
                    "physical": summonerMatchStats["physicalDamageDealtToChampions"],
                    "true": summonerMatchStats["trueDamageDealtToChampions"],
                    "selfMitigated": summonerMatchStats["damageSelfMitigated"],
                    "towerdamage": summonerMatchStats["damageDealtToTurrets"]
                },
                "ccScore": summonerMatchStats["timeCCingOthers"],
                "visionScore": summonerMatchStats["visionScore"],
                #TODO different Wards (sightward vs visionward)
                "summonerTimeline": summonerTimeline if matchdetails["info"]["gameMode"] == "CLASSIC" else None,
                "opponentTimeline": opponentTimeline if matchdetails["info"]["gameMode"] == "CLASSIC" else None,
            },
            "teammates": teammates,
            "opponents": opponents,
            "runes": {
                "keystoneId": summonerMatchStats["perks"]["styles"][0]["selections"][0]["perk"],
                "primary1": summonerMatchStats["perks"]["styles"][0]["selections"][1]["perk"],
                "primary2": summonerMatchStats["perks"]["styles"][0]["selections"][2]["perk"],
                "primary3": summonerMatchStats["perks"]["styles"][0]["selections"][3]["perk"],
                "secondary1": summonerMatchStats["perks"]["styles"][1]["selections"][0]["perk"],
                "secondary2": summonerMatchStats["perks"]["styles"][1]["selections"][1]["perk"],
                "shard1": summonerMatchStats["perks"]["statPerks"]["offense"],
                "shard2": summonerMatchStats["perks"]["statPerks"]["flex"],
                "shard3": summonerMatchStats["perks"]["statPerks"]["defense"]
            }
        }

        db.append(dbentry)
        
        bar.next()

    bar.finish()
    print(f"saved {len(db)} from {len(matches)} games")
    return db

client = None
db = None
def updateDB(entries):
    global client
    client = pymongo.MongoClient("mongodb://localhost:27017/")
    #dbtest = client["lolstatstest"]

    """ colMatches = dbtest["matches"]

    for entry in entries:
        if not colMatches.find_one({"matchId": entry['game']['matchId']}):
            colMatches.insert_one({"matchId": entry['game']['matchId']})

            data = { "_id": entry['game']['championId'], "name": entry['game']['championName'] }
            dbtest["championInfo"].update_one(data, {"$set": data}, upsert=True)
            
            #colChampion = id, champId, gamemode, lane (individual position), games
            filter = { "championId": entry['game']['championId'], "gameMode": entry['game']['gameMode'], "individualPosition": entry['game']['individualPosition'] }
            docChampion = dbtest["champion"].find_one(filter)
            if docChampion:
                games = docChampion["games"] + 1
            else:
                games = 1
            dbtest["champion"].update_one(filter, {"$set": { "games": games }}, upsert=True) """

    global db
    db = client["lolstats"]

    #delete collection only for testing purposes
    db["matches"].drop()
    db["championInfo"].drop()
    db["champion"].drop()
    db["statsbreakdown"].drop()
    db["gamecounter"].drop()

    for entry in entries:
        if not db["matches"].find_one({"matchId": entry['game']['matchId']}):
            db["matches"].insert_one({"matchId": entry['game']['matchId']})

            #Save Champion id and name
            data = { "_id": entry['game']['championId'], "name": entry['game']['championName'] }
            db["championInfo"].update_one(data, {"$set": data}, upsert=True)

            filter = { "championId": entry['game']['championId'], "gameMode": entry['game']['gameMode'], "individualPosition": entry['game']['individualPosition'] }
            docChampion = db["champion"].find_one(filter)
            if docChampion:
                updateChampion(docChampion["_id"], entry)
            else:
                insertChampion(entry)

def updateChampion(uid, entry):
    docChampion = db["champion"].find_one({ "_id": uid })
    updateStatsSummoner(docChampion["statsbreakdownId"], entry)

def insertChampion(entry):
    statsbreakdownId = insertStatsSummoner(entry)
    data = { 
        "championId": entry['game']['championId'], 
        "gameMode": entry['game']['gameMode'], 
        "individualPosition": entry['game']['individualPosition'], 
        "statsbreakdownId": statsbreakdownId 
    }
    db["champion"].insert_one(data)

def updateStatsSummoner(uid, entry):
    docStats = db["statsbreakdown"].find_one({ "_id": uid })
    updateGamecounter(docStats["gamecounterId"], entry)

    totalGames = db["gamecounter"].find_one({ "_id": docStats["gamecounterId"] })["totalgames"]

    data = {
        "avgCcScore": (docStats["avgCcScore"] * totalGames + entry["stats"]["ccScore"]) / (totalGames + 1),
        "ctrlWards": docStats["ctrlWards"] + 1, #TODO Visionscore not in samplegames
    }
    db["statsbreakdown"].update_one({"_id": uid}, {"$set": data})

def insertStatsSummoner(entry):
    #TODO insert other collection first to get the uids
    gamecounterId = insertGamecounter(entry)

    data = {
        "gamecounterId": gamecounterId,
        "avgCcScore": entry["stats"]["ccScore"],
        "ctrlWards": 1, #TODO Wards and Visionscore not in entry
    }
    stats = db["statsbreakdown"].insert_one(data)
    return stats.inserted_id

def insertGamecounter(entry):
    data = {
        "totalgames": 1,
        "wins": int(entry["game"]["win"]),
        "blueSide": 1 if entry["game"]["teamId"] == 100 else 0,
        "blueWins": int(entry["game"]["win"]) if entry["game"]["teamId"] == 100 else 0,
        "redSide": 1 if entry["game"]["teamId"] == 200 else 0,
        "redWins": int(entry["game"]["win"]) if entry["game"]["teamId"] == 200 else 0,
        "avgGameDuration": entry["game"]["gameDuration"],
        "minGameDuration": entry["game"]["gameDuration"],
        "maxGameDuration": entry["game"]["gameDuration"]
    }
    if entry["game"]["gameMode"] != "ARAM":
            data.update({
                "minutes": {
                    str(len(entry["stats"]["summonerTimeline"]) - 1): 1
                }
            })
    gc = db["gamecounter"].insert_one(data)
    return gc.inserted_id

def updateGamecounter(uid, entry):
    docGamecounter = db["gamecounter"].find_one({ "_id": uid })
    data = {
        "totalgames": docGamecounter["totalgames"] + 1,
        "wins": docGamecounter["wins"] + int(entry["game"]["win"]),
        "blueSide": docGamecounter["blueSide"] + 1 if entry["game"]["teamId"] == 100 else docGamecounter["blueSide"],
        "blueWins": docGamecounter["blueWins"] + int(entry["game"]["win"]) if entry["game"]["teamId"] == 100 else docGamecounter["blueWins"],
        "redSide": docGamecounter["redSide"] + 1 if entry["game"]["teamId"] == 200 else docGamecounter["redSide"],
        "redWins": docGamecounter["redWins"] + int(entry["game"]["win"]) if entry["game"]["teamId"] == 200 else docGamecounter["redWins"],
        "avgGameDuration": (docGamecounter["totalgames"] * docGamecounter["avgGameDuration"] + entry["game"]["gameDuration"]) / (docGamecounter["totalgames"] + 1),
        "minGameDuration": entry["game"]["gameDuration"] if entry["game"]["gameDuration"] < docGamecounter["minGameDuration"] else docGamecounter["minGameDuration"],
        "maxGameDuration": entry["game"]["gameDuration"] if entry["game"]["gameDuration"] > docGamecounter["maxGameDuration"] else docGamecounter["maxGameDuration"]
    }
    if entry["game"]["gameMode"] != "ARAM":
        minutesStr = str(len(entry["stats"]["summonerTimeline"]) - 1)
        data.update({"minutes": docGamecounter["minutes"]})
        if minutesStr in docGamecounter["minutes"].keys():
            data["minutes"][minutesStr] = data["minutes"][minutesStr] + 1
        else:
            data["minutes"][minutesStr] = 1


    db["gamecounter"].update_one({"_id": uid}, {"$set": data})

def main():

    #db = getNGames(25)

    """ f = open("data/db_dump.json", "w")
    f.write(json.dumps(db))
    f.close() """

    with open("data/examplegames.json") as f:
        db = json.load(f)

    updateDB(db)



if __name__ == '__main__':
    main()

