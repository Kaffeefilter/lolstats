import configparser
import requests
import json
from ratelimit import limits, sleep_and_retry, RateLimitException
from backoff import on_exception, expo
from progress.bar import Bar
from pprint import pprint

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
def call_riot(url):
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


config = configparser.ConfigParser()
config.read("apikey.ini")
apikey = config["riotapi"]["apiKey"]

def getNGames(n):
    summonername = "pwain"
    region = "euw1"
    regionv5 = "europe"

    summoner = call_riot("https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-name/" + summonername)
    me = json.loads(summoner.text)

    runeslookup = generateRunesLookup()
    shardslookup = generateShardLookup()

    #get a list of the last n matches played
    #n = 100
    matches = []
    indexes = list(range(0, n, 100))
    indexes.append(n)
    prevIndex = -1
    for index in indexes:
        if prevIndex >= 0:
            r = call_riot(f"https://{regionv5}.api.riotgames.com/lol/match/v5/matches/by-puuid/{me['puuid']}/ids?start={prevIndex}&count={index - prevIndex}")
            matches.extend(json.loads(r.text))
        prevIndex = index

    #get list of ids of relevant gamemodes
    r = requests.get("https://static.developer.riotgames.com/docs/lol/queues.json")
    queues = json.loads(r.text)
    #gamefilter = [ queue["queueId"] for queue in queues if queue["notes"] == None if queue["description"] != None if "5v5" in queue["description"] ]
    gamefilter = [ queue["queueId"] for queue in queues if queue["notes"] == None if queue["description"] != None if "5v5" in queue["description"] or "Clash" in queue["description"] ]

    bar = Bar('Processing', max=n)
    db = []
    for match in matches:
        #get match details
        r = call_riot(f"https://{regionv5}.api.riotgames.com/lol/match/v5/matches/{match}")
        if not r.ok:
            bar.next()
            continue
        matchdetails = json.loads(r.text)
        if matchdetails["info"]["queueId"] not in gamefilter:
            bar.next()
            continue     

        #get match timeline
        r = call_riot(f"https://{regionv5}.api.riotgames.com/lol/match/v5/matches/{match}/timeline")
        matchTimeline = json.loads(r.text)
        
        #save last entry for debug purposes
        """ f = open("data/last_match.json", "w")
        f.write(json.dumps(matchdetails, indent=4))
        f.close()

        f = open("data/last_timeline.json", "w")
        f.write(json.dumps(matchTimeline, indent=4))
        f.close() """

        #get the right stats
        for participant in matchdetails["info"]["participants"]:
            if participant["summonerName"] == summonername:
                summonerMatchStats = participant

        #get the right team stats
        for team in matchdetails["info"]["teams"]:
            if team["teamId"] == summonerMatchStats["teamId"]:
                teamStats = team

        #calculate team kills since there is no data for it
        teamKills = 0
        for participant in matchdetails["info"]["participants"]:
            if participant["teamId"] == summonerMatchStats["teamId"]:
                teamKills += participant["kills"]

        #get opponents stats
        for participant in matchdetails["info"]["participants"]:
            if (
                participant["teamId"] != summonerMatchStats["teamId"] and 
                participant["individualPosition"] == summonerMatchStats["individualPosition"]
            ):
                opponentMatchStats = participant

        #get timeline id for summoner and opponent
        for participant in matchTimeline["info"]["participants"]:
            if participant["puuid"] == summonerMatchStats["puuid"]:
                summonerTimelineId = participant["participantId"]
            if participant["puuid"] == opponentMatchStats["puuid"]:
                opponentTimelineId = participant["participantId"]

        #get timelinestats
        summonerTimeline = []
        opponentTimeline = []
        if matchdetails["info"]["gameMode"] == "CLASSIC":
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

        #get teammates and opponents
        teammates = []
        opponents = []
        for participant in matchdetails["info"]["participants"]:
            if participant["summonerName"] == summonername: continue
            elif participant["teamId"] == summonerMatchStats["teamId"]:
                teammates.append({"puuid": participant["puuid"], "name": participant["summonerName"]})
            else: 
                opponents.append({"puuid": participant["puuid"], "name": participant["summonerName"]})

        #for debugging
        tempdbentry = {
            "gameMode": matchdetails["info"]["gameMode"],
            "summonerMatchStats": summonerMatchStats,
            "opponentMatchStats": opponentMatchStats,
            "teamStats": teamStats,
            "teamKills": teamKills,
            "summonerTimelineId": summonerTimelineId,
            "opponentTimelineId": opponentTimelineId,
            "summonerTimeline": summonerTimeline,
            "opponentTimeline": opponentTimeline,
            "teammates": teammates,
            "opponents":opponents
        }
        db.append(tempdbentry)

        #TODO here
        bar.next()
        continue

        dbentry = {
            "game": {
                "championId": summonerMatchStats["championId"],
                "teamId": summonerMatchStats["teamId"],
                "queueId": matchdetails["queueId"],
                "gameMode": matchdetails["gameMode"],
                "win": summonerMatchStats["stats"]["win"],
                "gameDuration": matchdetails["gameDuration"],
                "role": summonerMatchStats["timeline"]["role"],
                "lane": summonerMatchStats["timeline"]["lane"]
            },
            "stats": {
                "kda": {
                    "kills": summonerMatchStats["stats"]["kills"],
                    "deaths": summonerMatchStats["stats"]["deaths"],
                    "assists": summonerMatchStats["stats"]["assists"],
                    "double": summonerMatchStats["stats"]["doubleKills"],
                    "triple": summonerMatchStats["stats"]["tripleKills"],
                    "quadra": summonerMatchStats["stats"]["quadraKills"],
                    "penta": summonerMatchStats["stats"]["pentaKills"],
                    "unreal": summonerMatchStats["stats"]["unrealKills"],
                    "teamKills": teamKills
                },
                "damage": {
                    "total": summonerMatchStats["stats"]["totalDamageDealtToChampions"],
                    "magic": summonerMatchStats["stats"]["magicDamageDealtToChampions"],
                    "physical": summonerMatchStats["stats"]["physicalDamageDealtToChampions"],
                    "true": summonerMatchStats["stats"]["trueDamageDealtToChampions"],
                    "selfMitigated": summonerMatchStats["stats"]["damageSelfMitigated"],
                    "towerdamage": summonerMatchStats["stats"]["damageDealtToTurrets"]
                },
                "ccScore": summonerMatchStats["stats"]["timeCCingOthers"],
                "deltas": deltas,
                "csPerMinDeltas": summonerMatchStats["timeline"]["creepsPerMinDeltas"],
                #"csDiffPerMinDeltas": summonerMatchStats["timeline"]["csDiffPerMinDeltas"] if matchdetails["gameMode"] == "CLASSIC" else None,
                "totalCsScore": summonerMatchStats["stats"]["totalMinionsKilled"] + summonerMatchStats["stats"]["neutralMinionsKilled"],
                "totalOpponentCsScore": opponentMatchStats["stats"]["totalMinionsKilled"] + opponentMatchStats["stats"]["neutralMinionsKilled"] if matchdetails["gameMode"] == "CLASSIC" else None,
                "csDiffAt15": csdiff if matchdetails["gameMode"] == "CLASSIC" else None,
                "goldPerMinDeltas": summonerMatchStats["timeline"]["goldPerMinDeltas"],
                #"opponentsGoldPerMinDeltas": opponentMatchStats["timeline"]["goldPerMinDeltas"] if matchdetails["gameMode"] == "CLASSIC" else None,
                "totalGold": summonerMatchStats["stats"]["goldEarned"],
                "totalOpponentGold": opponentMatchStats["stats"]["goldEarned"] if matchdetails["gameMode"] == "CLASSIC" else None,
                "goldDiffAt15": golddiff if matchdetails["gameMode"] == "CLASSIC" else None,
                "xpPerMinDeltas": summonerMatchStats["timeline"]["xpPerMinDeltas"],
                #"xpDiffPerMinDeltas": summonerMatchStats["timeline"]["xpDiffPerMinDeltas"] if matchdetails["gameMode"] == "CLASSIC" else None,
                "xpDiffAt15": xpdiff if matchdetails["gameMode"] == "CLASSIC" else None,
                "champLevel": summonerMatchStats["stats"]["champLevel"],
                "opponentChampLevel": opponentMatchStats["stats"]["champLevel"] if matchdetails["gameMode"] == "CLASSIC" else None
            },
            "teammates": teammates,
            "opponents": opponents,
            "runes": {
                "keystoneId": summonerMatchStats["stats"]["perk0"],
                "primary1": summonerMatchStats["stats"]["perk1"],
                "primary2": summonerMatchStats["stats"]["perk2"],
                "primary3": summonerMatchStats["stats"]["perk3"],
                "secondary1": summonerMatchStats["stats"]["perk4"],
                "secondary2": summonerMatchStats["stats"]["perk5"],
                "shard1": summonerMatchStats["stats"]["statPerk0"],
                "shard2": summonerMatchStats["stats"]["statPerk1"],
                "shard3": summonerMatchStats["stats"]["statPerk2"]
            }
        }

        db.append(dbentry)
        
        bar.next()

        #save last entry for debug purposes
        """f = open("data/last_entry.json", "w")
        f.write(json.dumps(dbentry, indent=4))
        f.close()"""

    bar.finish()
    print(f"saved {len(db)} from {len(matches)} games")
    return db


def main():

    db = getNGames(100)

    f = open("data/db_dump.json", "w")
    f.write(json.dumps(db))
    f.close()



if __name__ == '__main__':
    main()

