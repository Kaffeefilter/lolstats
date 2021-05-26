import configparser
import requests
import json
from ratelimit import limits, sleep_and_retry
from requests.models import Response

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

config = configparser.ConfigParser()
config.read("apikey.ini")
apikey = config["riotapi"]["apiKey"]
summonername = config["riotapi"]["summonername"]

#summoner = requests.get("https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-name/" + summonername, headers={"X-Riot-Token": apikey})
summoner = call_riot("https://euw1.api.riotgames.com/lol/summoner/v4/summoners/by-name/" + summonername)
summonerJson = json.loads(summoner.text)
print(summonerJson["accountId"])
print(summonerJson["puuid"])
print(summonerJson["name"])