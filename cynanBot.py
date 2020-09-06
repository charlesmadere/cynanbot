from analogueStoreRepository import AnalogueStoreRepository
from authHelper import AuthHelper
from channelIdsRepository import ChannelIdsRepository
from datetime import datetime, timedelta
import json
import random
import requests
from twitchio.ext import commands
from user import User
from usersRepository import UsersRepository
from userTokensRepository import UserTokensRepository
from wordOfTheDayRepository import WordOfTheDayRepository

# https://github.com/TwitchIO/TwitchIO

class CynanBot(commands.Bot):
    def __init__(
        self,
        analogueStoreRepository: AnalogueStoreRepository,
        authHelper: AuthHelper,
        channelIdsRepository: ChannelIdsRepository,
        usersRepository: UsersRepository,
        userTokensRepository: UserTokensRepository,
        wordOfTheDayRepository: WordOfTheDayRepository
    ):
        super().__init__(
            irc_token = authHelper.getIrcAuthToken(),
            client_id = authHelper.getClientId(),
            nick = 'CynanBot',
            prefix = '!',
            initial_channels = [ user.getHandle() for user in usersRepository.getUsers() ]
        )

        if analogueStoreRepository == None:
            raise ValueError(f'analogueStoreRepository argument is malformed: \"{analogueStoreRepository}\"')
        elif channelIdsRepository == None:
            raise ValueError(f'channelIdsRepository argument is malformed: \"{channelIdsRepository}\"')
        elif userTokensRepository == None:
            raise ValueError(f'userTokensRepository argument is malformed: \"{userTokensRepository}\"')
        elif wordOfTheDayRepository == None:
            raise ValueError(f'wordOfTheDayRepository argument is malformed: \"{wordOfTheDayRepository}\"')

        self.__analogueStoreRepository = analogueStoreRepository
        self.__authHelper = authHelper
        self.__channelIdsRepository = channelIdsRepository
        self.__usersRepository = usersRepository
        self.__userTokensRepository = userTokensRepository
        self.__wordOfTheDayRepository = wordOfTheDayRepository

        self.__lastAnalogueStockMessageTimes = dict()
        self.__lastCynanMessageTime = datetime.now() - timedelta(days = 1)
        self.__lastDeerForceMessageTimes = dict()
        self.__lastWotdMessageTimes = dict()

    async def event_command_error(self, ctx, error):
        # prevents exceptions caused by people using commands for other bots
        pass

    async def event_message(self, message):
        if message.content == 'D e e R F o r C e':
            await self.__handleDeerForceMessage(message)
            return

        if message.author.name.lower() == 'CynanMachae'.lower():
            if await self.__handleMessageFromCynan(message):
                return

        await self.handle_commands(message)

    async def event_raw_pubsub(self, data):
        if 'error' in data and len(data['error']) >= 1:
            print(f'Received a pub sub error: {data}')

            if data['error'] == 'ERR_BADAUTH':
                self.__validateAndRefreshTokens()

            return
        elif 'type' not in data:
            print(f'Received a pub sub response without a type: {data}')
            return
        elif data['type'] == 'PONG' or data['type'] == 'RESPONSE':
            print(f'Received a general pub sub response: {data}')
            return
        elif data['type'] != 'MESSAGE' or 'data' not in data or 'message' not in data['data']:
            print(f'Received an unexpected pub sub response: {data}')
            return

        jsonResponse = json.loads(data['data']['message'])

        if jsonResponse['type'] == 'reward-redeemed':
            await self.__handleRewardRedeemed(jsonResponse)

    async def event_ready(self):
        print(f'{self.nick} is ready!')

        for user in self.__usersRepository.getUsers():
            handle = user.getHandle()
            accessToken = self.__userTokensRepository.getAccessToken(handle)

            channelId = self.__channelIdsRepository.fetchChannelId(
                handle = handle,
                clientId = self.__authHelper.getClientId(),
                accessToken = accessToken
            )

            # we could subscribe to multiple topics, but for now, just channel points
            topics = [ f'channel-points-channel-v1.{channelId}' ]

            # subscribe to pubhub channel points events
            await self.pubsub_subscribe(accessToken, *topics)

    async def __handleDeerForceMessage(self, message):
        now = datetime.now()
        delta = now - timedelta(minutes = 20)
        user = self.__usersRepository.getUser(message.channel.name)

        lastDeerForceMessageTime = None
        if user.getHandle() in self.__lastDeerForceMessageTimes:
            lastDeerForceMessageTime = self.__lastDeerForceMessageTimes[user.getHandle()]

        if lastDeerForceMessageTime == None or delta > lastDeerForceMessageTime:
            self.__lastDeerForceMessageTimes[user.getHandle()] = now
            await message.channel.send('D e e R F o r C e')

    async def __handleMessageFromCynan(self, message):
        now = datetime.now()
        delta = now - timedelta(minutes = 30)

        if delta > self.__lastCynanMessageTime:
            self.__lastCynanMessageTime = now
            await message.channel.send_me('waves to @CynanMachae')
            return True
        else:
            return False

    async def __handlePotdRewardRedeemed(
        self,
        userThatRedeemed: str,
        twitchUser: User,
        twitchChannel
    ):
        print(f'Sending {twitchUser.getHandle()}\'s POTD to {userThatRedeemed}...')

        try:
            picOfTheDay = twitchUser.fetchPicOfTheDay()
            await twitchChannel.send(f'@{userThatRedeemed} here\'s the POTD: {picOfTheDay}')
        except FileNotFoundError:
            await twitchChannel.send(f'@{twitchUser.getHandle()} POTD file is missing!')
        except ValueError:
            await twitchChannel.send(f'@{twitchUser.getHandle()} POTD content is malformed!')

    async def __handleRewardRedeemed(self, jsonResponse):
        redemptionJson = jsonResponse['data']['redemption']
        twitchChannelId = redemptionJson['channel_id']
        twitchUser = None

        for user in self.__usersRepository.getUsers():
            userChannelId = self.__channelIdsRepository.fetchChannelId(
                handle = user.getHandle(),
                clientId = self.__authHelper.getClientId(),
                accessToken = self.__userTokensRepository.getAccessToken(user.getHandle())
            )

            if twitchChannelId.lower() == userChannelId.lower():
                twitchUser = user
                break

        if twitchUser == None:
            raise RuntimeError(f'Unable to find User with channel ID: \"{twitchChannelId}\"')

        potdRewardId = twitchUser.getPicOfTheDayRewardId()

        if not twitchUser.isPicOfTheDayEnabled():
            return

        if potdRewardId == None or len(potdRewardId) == 0 or potdRewardId.isspace():
            # This twitch user hasn't yet found their Reward ID for POTD. So let's just
            # print out as much helpful data as possible and then return.
            newRewardId = redemptionJson['reward']['id']
            print(f'The Reward ID is: \"{newRewardId}\", and the JSON is: \"{redemptionJson}\"')
            return

        userThatRedeemed = redemptionJson['user']['login']
        twitchChannel = self.get_channel(twitchUser.getHandle())

        if redemptionJson['reward']['id'] == potdRewardId:
            await self.__handlePotdRewardRedeemed(userThatRedeemed, twitchUser, twitchChannel)

    def __validateAndRefreshTokens(self):
        print('Validating and refreshing tokens...')

        self.__authHelper.validateAndRefreshAccessTokens(
            users = self.__usersRepository.getUsers(),
            userTokensRepository = self.__userTokensRepository
        )

        print('Finished validating and refreshing tokens')

    @commands.command(name = 'analogue')
    async def command_analogue(self, ctx):
        user = self.__usersRepository.getUser(ctx.channel.name)

        if not user.isAnalogueEnabled():
            return

        now = datetime.now()
        delta = now - timedelta(minutes = 1)
        lastAnalogueStockMessageTime = None

        if user.getHandle() in self.__lastAnalogueStockMessageTimes:
            lastAnalogueStockMessageTime = self.__lastAnalogueStockMessageTimes[user.getHandle()]

        if lastAnalogueStockMessageTime == None or delta > lastAnalogueStockMessageTime:
            self.__lastAnalogueStockMessageTimes[user.getHandle()] = now
            storeStock = self.__analogueStoreRepository.fetchStoreStock()

            if storeStock == None:
                await ctx.send('Error reading products from Analogue store')
            elif len(storeStock) == 0:
                await ctx.send('Analogue store has nothing in stock')
            else:
                await ctx.send(f'Analogue products in stock: {storeStock}')

    @commands.command(name = 'cynanbot')
    async def command_cynanbot(self, ctx):
        user = self.__usersRepository.getUser(ctx.channel.name)
        commands = [ '!cynanbot', '!discord', '!pbs', '!time', '!twitter' ]

        if user.isAnalogueEnabled():
            commands.append('!analogue')

        if user.isEsWordOfTheDayEnabled():
            commands.append('!esword')

        if user.isJaWordOfTheDayEnabled():
            commands.append('!jaword')

        if user.isZhWordOfTheDayEnabled():
            commands.append('!zhword')

        commands.sort()
        commandsString = ', '.join(commands)

        await ctx.send(f'my commands: {commandsString}')

    @commands.command(name = 'discord')
    async def command_discord(self, ctx):
        user = self.__usersRepository.getUser(ctx.channel.name)
        discord = user.getDiscord()

        if discord == None or len(discord) == 0 or discord.isspace():
            await ctx.send(f'{user.getHandle()} has no discord link available')
        else:
            await ctx.send(f'{user.getHandle()}\'s discord: {discord}')

    @commands.command(name = 'esword')
    async def command_esword(self, ctx):
        user = self.__usersRepository.getUser(ctx.channel.name)

        if not user.isEsWordOfTheDayEnabled():
            return

        now = datetime.now()
        delta = now - timedelta(seconds = 30)
        lastWotdMessageTime = None

        if user.getHandle() in self.__lastWotdMessageTimes:
            lastWotdMessageTime = self.__lastWotdMessageTimes[user.getHandle()]

        if lastWotdMessageTime == None or delta > lastWotdMessageTime:
            self.__lastWotdMessageTimes[user.getHandle()] = now
            esWotd = self.__wordOfTheDayRepository.fetchEsWotd()

            if esWotd == None:
                await ctx.send('Error fetching Spanish word of the day')
            elif esWotd.hasExamples():
                await ctx.send(f'{esWotd.getWord()} — {esWotd.getDefinition()}. Example: {esWotd.getForeignExample()} {esWotd.getEnglishExample()}')
            else:
                await ctx.send(f'{esWotd.getWord()} — {esWotd.getDefinition()}')

    @commands.command(name = 'jaword')
    async def command_jaword(self, ctx):
        user = self.__usersRepository.getUser(ctx.channel.name)

        if not user.isJaWordOfTheDayEnabled():
            return

        now = datetime.now()
        delta = now - timedelta(seconds = 30)
        lastWotdMessageTime = None

        if user.getHandle() in self.__lastWotdMessageTimes:
            lastWotdMessageTime = self.__lastWotdMessageTimes[user.getHandle()]

        if lastWotdMessageTime == None or delta > lastWotdMessageTime:
            self.__lastWotdMessageTimes[user.getHandle()] = now
            jaWotd = self.__wordOfTheDayRepository.fetchJaWotd()

            if jaWotd == None:
                await ctx.send('Error fetching Japanese word of the day')
            elif jaWotd.hasExamples():
                await ctx.send(f'{jaWotd.getWord()} ({jaWotd.getTransliteration()}) — {jaWotd.getDefinition()}. Example: {jaWotd.getForeignExample()}{jaWotd.getEnglishExample()}')
            else:
                await ctx.send(f'{jaWotd.getWord()} ({jaWotd.getTransliteration()}) — {jaWotd.getDefinition()}')

    @commands.command(name = 'pbs')
    async def command_pbs(self, ctx):
        user = self.__usersRepository.getUser(ctx.channel.name)
        speedrunProfile = user.getSpeedrunProfile()

        if speedrunProfile == None or len(speedrunProfile) == 0 or speedrunProfile.isspace():
            await ctx.send(f'{user.getHandle()} has no speedrun profile link available')
        else:
            await ctx.send(f'{user.getHandle()}\'s speedrun profile: {speedrunProfile}')

    @commands.command(name = 'time')
    async def command_time(self, ctx):
        user = self.__usersRepository.getUser(ctx.channel.name)
        timeZone = user.getTimeZone()
        timeFormat = "%A, %b %d, %Y %I:%M%p"

        if timeZone == None:
            now = datetime.now()
            formattedTime = now.strftime(timeFormat)
            await ctx.send(f'the system time for {self.nick} is {formattedTime}')
        else:
            now = datetime.now(timeZone)
            formattedTime = now.strftime(timeFormat)
            await ctx.send(f'the local time for {user.getHandle()} is {formattedTime}')

    @commands.command(name = 'twitter')
    async def command_twitter(self, ctx):
        user = self.__usersRepository.getUser(ctx.channel.name)
        twitter = user.getTwitter()

        if twitter == None or len(twitter) == 0 or twitter.isspace():
            await ctx.send(f'{user.getHandle()} has no twitter link available')
        else:
            await ctx.send(f'{user.getHandle()}\'s twitter: {twitter}')

    @commands.command(name = 'zhword')
    async def command_zhword(self, ctx):
        user = self.__usersRepository.getUser(ctx.channel.name)

        if not user.isZhWordOfTheDayEnabled():
            return

        now = datetime.now()
        delta = now - timedelta(seconds = 30)
        lastWotdMessageTime = None

        if user.getHandle() in self.__lastWotdMessageTimes:
            lastWotdMessageTime = self.__lastWotdMessageTimes[user.getHandle()]

        if lastWotdMessageTime == None or delta > lastWotdMessageTime:
            self.__lastWotdMessageTimes[user.getHandle()] = now
            zhWotd = self.__wordOfTheDayRepository.fetchZhWotd()

            if zhWotd == None:
                await ctx.send('Error fetching Mandarin Chinese word of the day')
            elif zhWotd.hasExamples():
                await ctx.send(f'{zhWotd.getWord()} ({zhWotd.getTransliteration()}) — {zhWotd.getDefinition()}. Example: {zhWotd.getForeignExample()}{zhWotd.getEnglishExample()}')
            else:
                await ctx.send(f'{zhWotd.getWord()} ({zhWotd.getTransliteration()}) — {zhWotd.getDefinition()}')
