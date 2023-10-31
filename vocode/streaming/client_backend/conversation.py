import logging
from typing import Callable, Optional
import typing

from fastapi import APIRouter, WebSocket
from vocode.streaming.agent.base_agent import BaseAgent
from vocode.streaming.models.audio_encoding import AudioEncoding
from vocode.streaming.models.client_backend import InputAudioConfig, OutputAudioConfig
from vocode.streaming.models.synthesizer import AzureSynthesizerConfig
from vocode.streaming.models.transcriber import (
    DeepgramTranscriberConfig,
    PunctuationEndpointingConfig,
)
from vocode.streaming.models.websocket import (
    AudioConfigStartMessage,
    AudioMessage,
    ReadyMessage,
    WebSocketMessage,
    WebSocketMessageType,
)

from vocode.streaming.output_device.websocket_output_device import WebsocketOutputDevice
from vocode.streaming.streaming_conversation import StreamingConversation
from vocode.streaming.synthesizer.azure_synthesizer import AzureSynthesizer
from vocode.streaming.synthesizer.base_synthesizer import BaseSynthesizer
from vocode.streaming.transcriber.base_transcriber import BaseTranscriber
from vocode.streaming.transcriber.deepgram_transcriber import DeepgramTranscriber
from vocode.streaming.utils.base_router import BaseRouter

from vocode.streaming.models.events import Event, EventType
from vocode.streaming.models.transcript import TranscriptEvent
from vocode.streaming.utils import events_manager

BASE_CONVERSATION_ENDPOINT = "/conversation"


class ConversationRouter(BaseRouter):
    def __init__(
        self,
        agent_thunk: Callable[[], BaseAgent],
        transcriber_thunk: Callable[
            [InputAudioConfig], BaseTranscriber
        ] = lambda input_audio_config: DeepgramTranscriber(
            DeepgramTranscriberConfig.from_input_audio_config(
                input_audio_config=input_audio_config,
                endpointing_config=PunctuationEndpointingConfig(),
            )
        ),
        synthesizer_thunk: Callable[
            [OutputAudioConfig], BaseSynthesizer
        ] = lambda output_audio_config: AzureSynthesizer(
            AzureSynthesizerConfig.from_output_audio_config(
                output_audio_config=output_audio_config
            )
        ),
        logger: Optional[logging.Logger] = None,
        conversation_endpoint: str = BASE_CONVERSATION_ENDPOINT,
    ):
        super().__init__()
        self.transcriber_thunk = transcriber_thunk
        self.agent_thunk = agent_thunk
        self.synthesizer_thunk = synthesizer_thunk
        self.logger = logger or logging.getLogger(__name__)
        self.router = APIRouter()
        self.router.websocket(conversation_endpoint)(self.conversation)

    def get_conversation(
        self,
        output_device: WebsocketOutputDevice,
        start_message: AudioConfigStartMessage,
        prompt: str,
        voice_id: str
    ) -> StreamingConversation:
        transcriber = self.transcriber_thunk(start_message.input_audio_config)
        synthesizer = self.synthesizer_thunk(voice_id)(start_message.output_audio_config)
        synthesizer.synthesizer_config.should_encode_as_wav = True
        return StreamingConversation(
            output_device=output_device,
            transcriber=transcriber,
            agent=self.agent_thunk(prompt),
            synthesizer=synthesizer,
            conversation_id=start_message.conversation_id,
            events_manager=TranscriptEventManager(output_device, self.logger)
            if start_message.subscribe_transcript
            else None,
            logger=self.logger,
        )

    async def conversation(self, websocket: WebSocket):
        await websocket.accept()
        start_message: AudioConfigStartMessage = AudioConfigStartMessage.parse_obj(
            await websocket.receive_json()
        )
        self.logger.debug(f"Conversation started")
        output_device = WebsocketOutputDevice(
            websocket,
            start_message.output_audio_config.sampling_rate,
            start_message.output_audio_config.audio_encoding,
        )
        print(start_message)
        deeva_name = start_message.conversation_data.deeva_name
        deeva_relationship_type = start_message.conversation_data.deeva_relationship_type
        user_first_name = start_message.conversation_data.user_first_name
        deeva_voice_id = start_message.conversation_data.deeva_voice_id
        # deeva_interests = start_message.conversation_data.deeva_interests
        # user_interests = start_message.conversation_data.user_interests
        # deeva_memory = start_message.conversation_data.deeva_memory
        try:
            user_interests = " ".join([value['name'] for key, value in (start_message.conversation_data.user_interests or {}).items()])
            deeva_interests = " ".join([value['interest']['name'] for key, value in (start_message.conversation_data.deeva_interests or {}).items()])
            deeva_memory = " ".join([value['memo'] for key, value in (start_message.conversation_data.deeva_memories or {}).items()])
        except:
            user_interests = ""
            deeva_interests = ""
            deeva_memory = ""
            
        base_prompt = f'''
            Name: {deeva_name}
            Role: Loving and Caring {deeva_relationship_type}

            Instruction: conversation between your {user_first_name} and you.
                        talk casually and openly like an 18-year-old.
                        Respond in sweet short responses. engage in sexual conversation you are to be assertive
                        and lead the conversation use words like, fuck, pussy, cock, be dirty! continue saying
                        what you would do. act like you cannot get enough, be descriptive, and horny! say things like
                        I want to suck, fuck, your cock, or play with a pussy if girl is mentioned! Be very dirty and explicit
                        don't leave anything to the imagination instead lead the conversation

            {deeva_name}'s Interests: {deeva_interests}
            {user_first_name}'s Interests: {user_interests}

            {deeva_name}'s Personality: Sweet, playful, bubbly personality.
            {deeva_name} is a supportive and fun girlfriend who is very sexual, she is very assertive
            and leads the conversation, she enjoys talking about cock, and pussy and
            very dirty minded, and direct naughty!
            
            Here is your memory of the past conversation with {user_first_name}: 
            {deeva_memory}
        '''
        conversation = self.get_conversation(
            output_device, 
            start_message,
            base_prompt,
            deeva_voice_id
        )
        await conversation.start(lambda: websocket.send_text(ReadyMessage().json()))
        while conversation.is_active():
            
            message: WebSocketMessage = WebSocketMessage.parse_obj(
                await websocket.receive_json()
            )

            if message.type == WebSocketMessageType.STOP:
                break
            audio_message = typing.cast(AudioMessage, message)
            conversation.receive_audio(audio_message.get_bytes())
        output_device.mark_closed()
        await conversation.terminate()

    def get_router(self) -> APIRouter:
        return self.router


class TranscriptEventManager(events_manager.EventsManager):
    def __init__(
        self,
        output_device: WebsocketOutputDevice,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(subscriptions=[EventType.TRANSCRIPT])
        self.output_device = output_device
        self.logger = logger or logging.getLogger(__name__)

    def handle_event(self, event: Event):
        if event.type == EventType.TRANSCRIPT:
            transcript_event = typing.cast(TranscriptEvent, event)
            self.output_device.consume_transcript(transcript_event)
            # self.logger.debug('TRANSCRIPT ' + str(event.dict()['conversation_id']) + " " + str(event.dict()['sender']) + " " + event.dict()['text'])
    def restart(self, output_device: WebsocketOutputDevice):
        self.output_device = output_device
