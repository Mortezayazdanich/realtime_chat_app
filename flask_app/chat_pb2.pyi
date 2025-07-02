from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ChatMessage(_message.Message):
    __slots__ = ("sender", "content", "timestamp")
    SENDER_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    sender: str
    content: str
    timestamp: int
    def __init__(self, sender: _Optional[str] = ..., content: _Optional[str] = ..., timestamp: _Optional[int] = ...) -> None: ...

class SendMessageRequest(_message.Message):
    __slots__ = ("message",)
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    message: ChatMessage
    def __init__(self, message: _Optional[_Union[ChatMessage, _Mapping]] = ...) -> None: ...

class SendMessageResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StreamMessagesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
