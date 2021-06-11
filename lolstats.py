import configparser
import requests
import json
from ratelimit import limits, sleep_and_retry
from pprint import pprint

#ratelimit imposed by Riot
#20 requests every 1 seconds(s)
#100 requests every 2 minutes(s)
@sleep_and_retry
@limits(calls=20, period=1)
@sleep_and_retry
@limits(calls=100, period=120)
def call_riot(url):
    response = requests.get(url, headers={"X-Riot-Token": apikey})
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

summonername = "pwain"
region = "euw1"

summoner = call_riot("https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-name/" + summonername)
me = json.loads(summoner.text)

runeslookup = generateRunesLookup()
shardslookup = generateShardLookup()

#get a list of the last n matches played
#endIndex from response is beginIndex for next call
n = 100
endIndex = 0
matches = []
while endIndex < n:
    r = call_riot(f"https://{region}.api.riotgames.com/lol/match/v4/matchlists/by-account/{me['accountId']}?beginIndex={endIndex}")
    matchlist = json.loads(r.text)
    for match in matchlist["matches"]:
        matches.append({
            "gameId": match["gameId"],
            "queue": match["queue"],
            "timestamp": match["timestamp"]
        })
    endIndex = matchlist["endIndex"]

db = []
for match in matches:
    print(f"get match {match['gameId']}")
    #get match details
    r = call_riot(f"https://{region}.api.riotgames.com/lol/match/v4/matches/{match['gameId']}")
    matchdetails = json.loads(r.text)
    print(r.status_code)

    print(f"get timeline for match {match['gameId']}")
    #get match timeline
    r = call_riot(f"https://{region}.api.riotgames.com/lol/match/v4/timelines/by-match/{match['gameId']}")
    matchTimeline = json.loads(r.text)
    print(r.status_code)

    #save last entry for debug purposes
    f = open("data/last_match.json", "w")
    f.write(json.dumps(matchdetails, indent=4))
    f.close()

    f = open("data/last_timeline.json", "w")
    f.write(json.dumps(matchTimeline, indent=4))
    f.close()

    #search for summonerId in match
    for participant in matchdetails["participantIdentities"]:
        if summonername == participant["player"]["summonerName"]:
            summonerMatchId = participant["participantId"]
            break
    
    #get the right stats
    if matchdetails["participants"][summonerMatchId - 1]["participantId"] == summonerMatchId:   #most of the time the right index is Id - 1
        summonerMatchStats = matchdetails["participants"][summonerMatchId - 1]
    else:
        for participant in matchdetails["participants"]:
            if participant["participantId"] == summonerMatchId:
                summonerMatchStats = participant
                break

    #get the right team
    for team in matchdetails["teams"]:
        if team["teamId"] == summonerMatchStats["teamId"]:
            teamStats = team

    #calculate team kills since there is no data for it
    teamKills = 0
    for participant in matchdetails["participants"]:
        if participant["teamId"] == summonerMatchStats["teamId"]:
            teamKills += participant["stats"]["kills"]

    #get all deltas
    # deltas = []
    # for delta in summonerMatchStats["timeline"]["xpPerMinDeltas"]:
    #     deltas.append(delta)
    deltas = [delta for delta in summonerMatchStats["timeline"]["xpPerMinDeltas"]]

    #get opponents stats
    for participant in matchdetails["participants"]:
        if (
            participant["teamId"] != summonerMatchStats["teamId"] and 
            participant["timeline"]["role"] == summonerMatchStats["timeline"]["role"] and
            participant["timeline"]["lane"] == summonerMatchStats["timeline"]["lane"]
        ):
            opponentMatchStats = participant

    #calculate diff at 15 for cs, gold and xp
    csdiff = golddiff = xpdiff = 0
    if "15" in matchTimeline["frames"] and matchdetails["gameMode"] == "CLASSIC":
        for participantFrame in matchTimeline["frames"]["15"]["participantFrames"]:
            if participantFrame["participantId"] == summonerMatchStats["participantId"]:
                csdiff += participantFrame["minionsKilled"] + participantFrame["jungleMinionsKilled"]
                golddiff += participantFrame["totalGold"]
                xpdiff += participantFrame["xp"]
            elif participantFrame["participantId"] == opponentMatchStats["participantId"]:
                csdiff -= participantFrame["minionsKilled"] - participantFrame["jungleMinionsKilled"]
                golddiff -= participantFrame["totalGold"]
                xpdiff -= participantFrame["xp"]

    #get teammates
    teammates = []
    opponents = []
    for player in matchdetails["participantIdentities"]:
        if player["participantId"] == summonerMatchId: continue
        for playerstats in matchdetails["participants"]:
            if playerstats["participantId"] == player["participantId"]:
                if playerstats["teamId"] == summonerMatchStats["teamId"]:
                    teammates.append({"id": player["player"]["accountId"], "name": player["player"]["summonerName"]})
                else:
                    opponents.append({"id": player["player"]["accountId"], "name": player["player"]["summonerName"]})


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
            "csDiffPerMinDeltas": summonerMatchStats["timeline"]["csDiffPerMinDeltas"] if matchdetails["gameMode"] == "CLASSIC" else None, #TODO csDiffPerMinDeltas not always present ?!?!?!
            "totalCsScore": summonerMatchStats["stats"]["totalMinionsKilled"] + summonerMatchStats["stats"]["neutralMinionsKilled"],
            "totalOpponentScScore": opponentMatchStats["stats"]["totalMinionsKilled"] + opponentMatchStats["stats"]["neutralMinionsKilled"] if matchdetails["gameMode"] == "CLASSIC" else None,
            "csDiffAt15": csdiff if matchdetails["gameMode"] == "CLASSIC" else None,
            "goldPerMinDeltas": summonerMatchStats["timeline"]["goldPerMinDeltas"],
            "opponentsGoldPerMinDeltas": opponentMatchStats["timeline"]["goldPerMinDeltas"] if matchdetails["gameMode"] == "CLASSIC" else None,
            "totalGold": summonerMatchStats["stats"]["goldEarned"],
            "totalOpponentGold": opponentMatchStats["stats"]["goldEarned"] if matchdetails["gameMode"] == "CLASSIC" else None,
            "goldDiffAt15": golddiff if matchdetails["gameMode"] == "CLASSIC" else None,
            "xpPerMinDeltas": summonerMatchStats["timeline"]["xpPerMinDeltas"],
            "xpDiffPerMinDeltas": summonerMatchStats["timeline"]["xpDiffPerMinDeltas"] if matchdetails["gameMode"] == "CLASSIC" else None,
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

    #save last entry for debug purposes
    f = open("data/last_entry.json", "w")
    f.write(json.dumps(dbentry, indent=4))
    f.close()


f = open("data/db_dump.json", "w")
f.write(json.dumps(db, indent=4))
f.close()




