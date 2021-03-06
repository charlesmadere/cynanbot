import json
import locale
from datetime import timedelta
from typing import List

import requests
from requests import ConnectionError, HTTPError, Timeout
from urllib3.exceptions import MaxRetryError, NewConnectionError

import CynanBotCommon.utils as utils
from CynanBotCommon.timedDict import TimedDict
from locationsRepository import Location


class WeatherRepository():

    def __init__(
        self,
        oneWeatherApiKey: str,
        iqAirApiKey: str = None,
        cacheTimeDelta: timedelta = timedelta(hours=1, minutes=30)
    ):
        if not utils.isValidStr(oneWeatherApiKey):
            raise ValueError(f'oneWeatherApiKey argument is malformed: \"{oneWeatherApiKey}\"')
        elif cacheTimeDelta is None:
            raise ValueError(f'cacheTimeDelta argument is malformed: \"{cacheTimeDelta}\"')

        if not utils.isValidStr(iqAirApiKey):
            print(f'IQAir API key is malformed: \"{iqAirApiKey}\". This won\'t prevent us from fetching weather, but it will prevent us from fetching the current air quality conditions at the given location.')

        self.__iqAirApiKey = iqAirApiKey
        self.__oneWeatherApiKey = oneWeatherApiKey
        self.__cache = TimedDict(timeDelta=cacheTimeDelta)
        self.__conditionIcons = self.__createConditionIconsDict()

    def __chooseTomorrowFromForecast(self, jsonResponse: dict):
        currentSunrise = jsonResponse['current']['sunrise']
        currentSunset = jsonResponse['current']['sunset']

        for dayJson in jsonResponse['daily']:
            if dayJson['sunrise'] > currentSunrise and dayJson['sunset'] > currentSunset:
                return dayJson

        raise RuntimeError(f'Unable to find viable tomorrow data in JSON response: \"{jsonResponse}\"')

    def __createConditionIconsDict(self):
        # This dictionary is built from the Weather Condition Codes listed here:
        # https://openweathermap.org/weather-conditions#Weather-Condition-Codes-2

        icons = dict()
        icons['200'] = '⛈️'
        icons['201'] = icons['200']
        icons['202'] = icons['200']
        icons['210'] = '🌩️'
        icons['211'] = icons['210']
        icons['212'] = icons['211']
        icons['221'] = icons['200']
        icons['230'] = icons['200']
        icons['231'] = icons['200']
        icons['232'] = icons['200']
        icons['300'] = '☔'
        icons['301'] = icons['300']
        icons['310'] = icons['300']
        icons['311'] = icons['300']
        icons['313'] = icons['300']
        icons['500'] = icons['300']
        icons['501'] = '🌧️'
        icons['502'] = icons['501']
        icons['503'] = icons['501']
        icons['504'] = icons['501']
        icons['520'] = icons['501']
        icons['521'] = icons['501']
        icons['522'] = icons['501']
        icons['531'] = icons['501']
        icons['600'] = '❄️'
        icons['601'] = icons['600']
        icons['602'] = '🌨️'
        icons['711'] = '🌫️'
        icons['721'] = icons['711']
        icons['731'] = icons['711']
        icons['741'] = icons['711']
        icons['762'] = '🌋'
        icons['771'] = '🌬'
        icons['781'] = '🌪️'
        icons['801'] = '☁️'
        icons['802'] = icons['801']
        icons['803'] = icons['801']
        icons['804'] = icons['801']

        return icons

    def __fetchAirQuality(self, location: Location):
        if location is None:
            raise ValueError(f'location argument is malformed: \"{location}\"')

        if not utils.isValidStr(self.__iqAirApiKey):
            return None

        # Retrieve air quality from: https://api-docs.iqair.com/
        # Doing this requires an API key, which you can get here:
        # https://www.iqair.com/us/commercial/air-quality-monitors/airvisual-platform/api

        requestUrl = "https://api.airvisual.com/v2/nearest_city?key={}&lat={}&lon={}".format(
            self.__iqAirApiKey, location.getLatitude(), location.getLongitude())

        
        rawResponse = None

        try:
            rawResponse = requests.get(url=requestUrl, timeout=utils.getDefaultTimeout())
        except (ConnectionError, HTTPError, MaxRetryError, NewConnectionError, Timeout) as e:
            print(f'Exception occurred when attempting to fetch air quality from IQAir: {e}')

        if rawResponse is None:
            print(f'rawResponse is malformed: \"{rawResponse}\"')
            return None

        jsonResponse = rawResponse.json()

        if jsonResponse.get('status') != 'success':
            return None

        return jsonResponse['data']['current']['pollution']['aqius']

    def fetchWeather(self, location: Location):
        if location is None:
            raise ValueError(f'location argument is malformed: \"{location}\"')

        cacheValue = self.__cache[location.getId()]

        if cacheValue is not None:
            return cacheValue

        print(f'Refreshing weather for \"{location.getId()}\"... ({utils.getNowTimeText()})')

        # Retrieve weather report from https://openweathermap.org/api/one-call-api
        # Doing this requires an API key, which you can get here:
        # https://openweathermap.org/api

        requestUrl = "https://api.openweathermap.org/data/2.5/onecall?appid={}&lat={}&lon={}&exclude=minutely,hourly&units=metric".format(
            self.__oneWeatherApiKey, location.getLatitude(), location.getLongitude())

        rawResponse = None

        try:
            rawResponse = requests.get(url=requestUrl, timeout=utils.getDefaultTimeout())
        except (ConnectionError, HTTPError, MaxRetryError, NewConnectionError, Timeout) as e:
            print(f'Exception occurred when attempting to fetch weather conditions from Open Weather: {e}')

        if rawResponse is None:
            print(f'rawResponse is malformed: \"{rawResponse}\"')
            del self.__cache[location.getId()]
            return None

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

                if event is not None and len(event) >= 1:
                    if senderName is None or len(senderName) == 0:
                        alerts.append(f'Alert: {event}.')
                    else:
                        alerts.append(f'Alert from {senderName}: {event}.')

        tomorrowsJson = self.__chooseTomorrowFromForecast(jsonResponse)
        tomorrowsHighTemperature = tomorrowsJson['temp']['max']
        tomorrowsLowTemperature = tomorrowsJson['temp']['min']

        tomorrowsConditions = list()
        if 'weather' in tomorrowsJson and len(tomorrowsJson['weather']) >= 1:
            for conditionJson in tomorrowsJson['weather']:
                tomorrowsConditions.append(conditionJson['description'])

        airQuality = self.__fetchAirQuality(location)
        weatherReport = None

        try:
            weatherReport = WeatherReport(
                airQuality=airQuality,
                humidity=humidity,
                pressure=pressure,
                temperature=temperature,
                tomorrowsHighTemperature=tomorrowsHighTemperature,
                tomorrowsLowTemperature=tomorrowsLowTemperature,
                alerts=alerts,
                conditions=conditions,
                tomorrowsConditions=tomorrowsConditions
            )
        except ValueError:
            print(f'Weather Report for \"{location.getId()}\" has a data error')

        if weatherReport is None:
            del self.__cache[location.getId()]
        else:
            self.__cache[location.getId()] = weatherReport

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


class WeatherReport():

    def __init__(
        self,
        airQuality: int,
        humidity: float,
        pressure: float,
        temperature: float,
        tomorrowsHighTemperature: float,
        tomorrowsLowTemperature: float,
        alerts: List[str],
        conditions: List[str],
        tomorrowsConditions: List[str]
    ):
        if not utils.isValidNum(humidity):
            raise ValueError(f'humidity argument is malformed: \"{humidity}\"')
        elif not utils.isValidNum(pressure):
            raise ValueError(f'pressure argument is malformed: \"{pressure}\"')
        elif not utils.isValidNum(temperature):
            raise ValueError(f'temperature argument is malformed: \"{temperature}\"')
        elif not utils.isValidNum(tomorrowsHighTemperature):
            raise ValueError(f'tomorrowsHighTemperature argument is malformed: \"{tomorrowsHighTemperature}\"')
        elif not utils.isValidNum(tomorrowsLowTemperature):
            raise ValueError(f'tomorrowsLowTemperature argument is malformed: \"{tomorrowsLowTemperature}\"')

        self.__airQuality = airQuality
        self.__humidity = int(round(humidity))
        self.__pressure = int(round(pressure))
        self.__temperature = temperature
        self.__tomorrowsHighTemperature = tomorrowsHighTemperature
        self.__tomorrowsLowTemperature = tomorrowsLowTemperature
        self.__alerts = alerts
        self.__conditions = conditions
        self.__tomorrowsConditions = tomorrowsConditions

    def __cToF(self, celsius: float):
        return (celsius * (9 / 5)) + 32

    def getAirQuality(self):
        return self.__airQuality

    def getAirQualityStr(self):
        return locale.format_string("%d", self.getAirQuality(), grouping=True)

    def getAlerts(self):
        return self.__alerts

    def getConditions(self):
        return self.__conditions

    def getHumidity(self):
        return self.__humidity

    def getPressure(self):
        return self.__pressure

    def getPressureStr(self):
        return locale.format_string("%d", self.getPressure(), grouping=True)

    def getTemperature(self):
        return int(round(self.__temperature))

    def getTemperatureStr(self):
        return locale.format_string("%d", self.getTemperature(), grouping=True)

    def getTemperatureImperial(self):
        return int(round(self.__cToF(self.__temperature)))

    def getTemperatureImperialStr(self):
        return locale.format_string("%d", self.getTemperatureImperial(), grouping=True)

    def getTomorrowsConditions(self):
        return self.__tomorrowsConditions

    def getTomorrowsLowTemperature(self):
        return int(round(self.__tomorrowsLowTemperature))

    def getTomorrowsLowTemperatureStr(self):
        return locale.format_string("%d", self.getTomorrowsLowTemperature(), grouping=True)

    def getTomorrowsLowTemperatureImperial(self):
        return int(round(self.__cToF(self.__tomorrowsLowTemperature)))

    def getTomorrowsLowTemperatureImperialStr(self):
        return locale.format_string("%d", self.getTomorrowsLowTemperatureImperial(), grouping=True)

    def getTomorrowsHighTemperature(self):
        return int(round(self.__tomorrowsHighTemperature))

    def getTomorrowsHighTemperatureStr(self):
        return locale.format_string("%d", self.getTomorrowsHighTemperature(), grouping=True)

    def getTomorrowsHighTemperatureImperial(self):
        return int(round(self.__cToF(self.__tomorrowsHighTemperature)))

    def getTomorrowsHighTemperatureImperialStr(self):
        return locale.format_string("%d", self.getTomorrowsHighTemperatureImperial(), grouping=True)

    def hasAirQuality(self):
        return self.__airQuality is not None

    def hasAlerts(self):
        return self.__alerts is not None and len(self.__alerts) >= 1

    def hasConditions(self):
        return self.__conditions is not None and len(self.__conditions) >= 1

    def hasTomorrowsConditions(self):
        return self.__tomorrowsConditions is not None and len(self.__tomorrowsConditions) >= 1

    def toStr(self, delimiter: str = ', '):
        if delimiter is None:
            raise ValueError(f'delimiter argument is malformed: \"{delimiter}\"')

        temperature = f'🌡 Temperature is {self.getTemperatureStr()}°C ({self.getTemperatureImperialStr()}°F), '
        humidity = f'humidity is {self.getHumidity()}%, '

        airQuality = ''
        if self.hasAirQuality():
            airQuality = f'air quality is {self.getAirQualityStr()}, '

        pressure = f'and pressure is {self.getPressureStr()} hPa. '

        conditions = ''
        if self.hasConditions():
            conditionsJoin = delimiter.join(self.getConditions())
            conditions = f'Current conditions: {conditionsJoin}. '

        tomorrowsTemps = f'Tomorrow has a low of {self.getTomorrowsLowTemperatureStr()}°C ({self.getTomorrowsLowTemperatureImperialStr()}°F) and a high of {self.getTomorrowsHighTemperatureStr()}°C ({self.getTomorrowsHighTemperatureImperialStr()}°F). '

        tomorrowsConditions = ''
        if self.hasTomorrowsConditions():
            tomorrowsConditionsJoin = delimiter.join(self.getTomorrowsConditions())
            tomorrowsConditions = f'Tomorrow\'s conditions: {tomorrowsConditionsJoin}. '

        alerts = ''
        if self.hasAlerts():
            alertsJoin = ' '.join(self.getAlerts())
            alerts = f'🚨 {alertsJoin}'

        return f'{temperature}{humidity}{airQuality}{pressure}{conditions}{tomorrowsTemps}{tomorrowsConditions}{alerts}'
