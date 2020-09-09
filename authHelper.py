import json
import os
import requests
from typing import List
from user import User
from userTokensRepository import UserTokensRepository

# The authentication file should be formatted like this:
# {
#    "clientId": "", (taken from "Client ID" at https://dev.twitch.tv/console/apps/)
#    "clientSecret": "", (taken from "Client Secret" at https://dev.twitch.tv/console/apps/)
#    "ircAuthToken": "", (generated from https://twitchapps.com/tmi/)
# }

class AuthHelper():
    def __init__(self, authFile: str = "authFile.json"):
        if authFile == None or len(authFile) == 0 or authFile.isspace():
            raise ValueError(f'authFile argument is malformed: \"{authFile}\"')

        self.__authFile = authFile

        jsonContents = self.__readJson()
        clientId = None
        clientSecret = None
        ircAuthToken = None

        if 'clientId' in jsonContents:
            clientId = jsonContents['clientId']
        else:
            raise ValueError(f'Auth file ({authFile}) is missing \"clientId\"')

        if 'clientSecret' in jsonContents:
            clientSecret = jsonContents['clientSecret']
        else:
            raise ValueError(f'Auth file ({authFile}) is missing \"clientSecret\"')

        if 'ircAuthToken' in jsonContents:
            ircAuthToken = jsonContents['ircAuthToken']
        else:
            raise ValueError(f'Auth file ({authFile}) is missing \"ircAuthToken\"')

        if clientId == None or len(clientId) == 0 or clientId.isspace():
            raise ValueError(f'Auth file ({authFile}) has malformed clientId: \"{clientId}\"')
        elif clientSecret == None or len(clientSecret) == 0 or clientSecret.isspace():
            raise ValueError(f'Auth file ({authFile}) has malformed clientSecret: \"{clientSecret}\"')
        elif ircAuthToken == None or len(ircAuthToken) == 0 or ircAuthToken.isspace():
            raise ValueError(f'Auth file ({ircAuthToken}) has malformed ircAuthToken: \"{ircAuthToken}\"')

        self.__clientId = clientId
        self.__clientSecret = clientSecret
        self.__ircAuthToken = ircAuthToken

    def getClientId(self):
        return self.__clientId

    def getClientSecret(self):
        return self.__clientSecret

    def getIrcAuthToken(self):
        return self.__ircAuthToken

    def __readJson(self):
        if not os.path.exists(self.__authFile):
            raise FileNotFoundError(f'Auth file not found: \"{self.__authFile}\"')

        with open(self.__authFile, 'r') as file:
            jsonContents = json.load(file)

        if jsonContents == None:
            raise IOError(f'Error reading from auth file: \"{self.__authFile}\"')

        return jsonContents

    def __refreshAccessToken(
        self,
        handle: str,
        userTokensRepository: UserTokensRepository
    ):
        refreshToken = userTokensRepository.getRefreshToken(handle)

        params = {
            'client_id': self.getClientId(),
            'client_secret': self.getClientSecret(),
            'grant_type': 'refresh_token',
            'refresh_token': refreshToken
        }

        rawResponse = requests.post(
            url = 'https://id.twitch.tv/oauth2/token',
            params = params
        )

        jsonResponse = json.loads(rawResponse.content)

        if 'access_token' not in jsonResponse or len(jsonResponse['access_token']) == 0:
            raise ValueError(f'Received malformed \"access_token\" for {handle}: {jsonResponse}')
        elif 'refresh_token' not in jsonResponse or len(jsonResponse['refresh_token']) == 0:
            raise ValueError(f'Received malformed \"refresh_token\" for {handle}: {jsonResponse}')

        userTokensRepository.setTokens(
            handle = handle,
            accessToken = jsonResponse['access_token'],
            refreshToken = jsonResponse['refresh_token']
        )

    def validateAndRefreshAccessTokens(
        self,
        users: List[User],
        userTokensRepository: UserTokensRepository
    ):
        if userTokensRepository == None:
            raise ValueError(f'userTokensRepository argument is malformed: \"{userTokensRepository}\"')

        if users == None or len(users) == 0:
            print(f'Given an empty list of users, skipping access token validation')
            return

        print(f'Validating access tokens for {len(users)} user(s)...')

        for user in users:
            handle = user.getHandle()
            accessToken = userTokensRepository.getAccessToken(handle)

            if accessToken == None:
                continue

            headers = {
                'Authorization': f'OAuth {accessToken}'
            }

            rawResponse = requests.get(
                url = 'https://id.twitch.tv/oauth2/validate',
                headers = headers
            )

            jsonResponse = json.loads(rawResponse.content)

            if 'client_id' not in jsonResponse or len(jsonResponse['client_id']) == 0:
                print(f'Refreshing access token for {handle}...')

                self.__refreshAccessToken(
                    handle = handle,
                    userTokensRepository = userTokensRepository
                )
