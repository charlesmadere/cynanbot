from authHelper import AuthHelper
from datetime import datetime, timedelta
import json
from location import Location
import requests
from weatherReport import WeatherReport

class WeatherRepository():

    def __init__(
        self,
        authHelper: AuthHelper,
        cacheTimeDelta = timedelta(hours = 1, minutes = 30)
    ):
        if authHelper == None:
            raise ValueError(f'authFile argument is malformed: \"{authFile}\"')

        self.__authHelper = authHelper
        self.__cacheTimeDelta = cacheTimeDelta
        self.__cacheTimes = dict()
        self.__conditionIcons = self.__createConditionIconsDict()
        self.__weatherReports = dict()

    def __createConditionIconsDict(self):
        icons = dict()
        icons['200'] = '⛈'
        icons['201'] = icons['200']
        icons['202'] = icons['200']
        icons['210'] = '🌩'
        icons['211'] = icons['210']
        icons['212'] = icons['210']
        icons['230'] = icons['200']
        icons['231'] = icons['230']
        icons['232'] = icons['230']
        icons['300'] = '☔️'
        icons['301'] = icons['300']
        icons['500'] = '🌧'
        icons['501'] = icons['500']
        icons['502'] = icons['500']
        icons['503'] = icons['500']
        icons['503'] = icons['500']
        icons['600'] = '❅'
        icons['601'] = icons['600']
        icons['602'] = icons['600']
        icons['741'] = '🌫'
        icons['781'] = '🌪'
        icons['802'] = '☁️'
        icons['803'] = icons['802']
        icons['804'] = icons['802']

        return icons

    def fetchWeather(self, location: Location):
        if location == None:
            raise ValueError(f'location argument is malformed: \"{location}\"')

        if location.getId() in self.__weatherReports and location.getId() in self.__cacheTimes:
            cacheTime = self.__cacheTimes[location.getId()] + self.__cacheTimeDelta

            if cacheTime > datetime.now():
                return self.__weatherReports[location.getId()]

        print(f'Refreshing weather for \"{location.getId()}\"...')

        oneWeatherApiKey = self.__authHelper.getOneWeatherApiKey()
        if oneWeatherApiKey == None or len(oneWeatherApiKey) == 0 or oneWeatherApiKey.isspace():
            raise RuntimeError(f'oneWeatherApiKey is malformed: \"{oneWeatherApiKey}\"')

        requestUrl = "https://api.openweathermap.org/data/2.5/onecall?appid={}&lat={}&lon={}&exclude=minutely,hourly&units=metric".format(
            oneWeatherApiKey, location.getLatitude(), location.getLongitude())

        rawResponse = requests.get(requestUrl)
        jsonResponse = rawResponse.json()

        currentJson = jsonResponse['current']
        humidity = currentJson['humidity']
        pressure = currentJson['pressure']
        temperature = currentJson['temp']

        conditions = list()
        if 'weather' in currentJson and len(currentJson['weather']) >= 1:
            for conditionJson in currentJson['weather']:
                conditions.append(self.__prettifyCondition(conditionJson))

        alerts = list()
        if 'alerts' in jsonResponse and len(jsonResponse['alerts']) >= 1:
            for alertJson in jsonResponse['alerts']:
                event = alertJson.get('event')
                senderName = alertJson.get('sender_name')

                if event != None and len(event) >= 1:
                    if senderName == None or len(senderName) == 0:
                        alerts.append(f'Alert: {event}.')
                    else:
                        alerts.append(f'Alert from {senderName}: {event}.')

        tomorrowsJson = jsonResponse['daily'][1]
        tomorrowsHighTemperature = tomorrowsJson['temp']['max']
        tomorrowsLowTemperature = tomorrowsJson['temp']['min']

        tomorrowsConditions = list()
        if 'weather' in tomorrowsJson and len(tomorrowsJson['weather']) >= 1:
            for conditionJson in tomorrowsJson['weather']:
                tomorrowsConditions.append(conditionJson['description'])

        weatherReport = None

        try:
            weatherReport = WeatherReport(
                humidity = humidity,
                pressure = pressure,
                temperature = temperature,
                tomorrowsHighTemperature = tomorrowsHighTemperature,
                tomorrowsLowTemperature = tomorrowsLowTemperature,
                alerts = alerts,
                conditions = conditions,
                tomorrowsConditions = tomorrowsConditions
            )
        except ValueError:
            print(f'Weather Report for \"{location.getId()}\" has a data error')

        if weatherReport == None:
            self.__weatherReports.pop(location.getId(), None)
            self.__cacheTimes.pop(location.getId(), None)
        else:
            self.__weatherReports[location.getId()] = weatherReport
            self.__cacheTimes[location.getId()] = datetime.now()

        return weatherReport

    def __prettifyCondition(self, conditionJson: dict):
        conditionIcon = ''
        if 'id' in conditionJson:
            id_ = str(conditionJson['id'])

            if id_ in self.__conditionIcons:
                icon = self.__conditionIcons[id_]
                conditionIcon = f'{icon} '

        conditionDescription = conditionJson['description']
        return f'{conditionIcon}{conditionDescription}'