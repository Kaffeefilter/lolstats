import configparser
import requests
import json
from ratelimit import limits, sleep_and_retry

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
        lookup["version"] = "11.11.1"
        for idx, tree in enumerate(runes):
            for jdx, slot in enumerate(tree["slots"]):
                for kdx, rune in enumerate(slot["runes"]):
                    lookup[rune["id"]] = str(idx) + str(jdx) + str(kdx)
    else:
        print("ddragon not reachable")
    
    print(json.dumps(lookup, indent=4))

config = configparser.ConfigParser()
config.read("apikey.ini")
apikey = config["riotapi"]["apiKey"]
summonername = config["riotapi"]["summonername"]

#summoner = call_riot("https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-name/" + summonername)
#summoner = json.loads(summoner.text)
#print(summoner["accountId"])
#print(summoner["puuid"])
#print(summoner["name"])

generateRunesLookup()