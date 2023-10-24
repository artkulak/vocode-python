from typing import Optional
from vocode.streaming.models.audio_encoding import AudioEncoding
from vocode.streaming.models.model import BaseModel


class InputAudioConfig(BaseModel):
    sampling_rate: int
    audio_encoding: AudioEncoding
    chunk_size: int
    downsampling: Optional[int] = None


class OutputAudioConfig(BaseModel):
    sampling_rate: int
    audio_encoding: AudioEncoding
    
class ConversationData(BaseModel):
    user_id: str
    user_first_name: str
    user_last_name: str
    user_interests: str
    deeva_profile_id: str
    deeva_memory: str
    deeva_name: str
    deeva_relationship_type: str
    deeva_interests: str
    
    
