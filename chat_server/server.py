# chat_server/server.py
import grpc
import time
import concurrent.futures
import threading
import collections
import chat_pb2
import chat_pb2_grpc
_CHAT_MESSAGES = collections.deque(maxlen=100)
_MESSAGE_CONDITION = threading.Condition()
class ChatServiceServicer(chat_pb2_grpc.ChatServiceServicer):
    """
    Implements the gRPC ChatService.
    Handles sending and streaming chat messages.
    """
    def SendMessage(self, request, context):
        """
        Handles unary RPC for sending a single message.
        Appends the new message to our in-memory storage and notifies
        all waiting streaming clients.
        """
        print(f"Received message: {request.message.sender}: {request.message.content}")
        with _MESSAGE_CONDITION:
            _CHAT_MESSAGES.append(request.message)
            _MESSAGE_CONDITION.notify_all()
        return chat_pb2.SendMessageResponse()
    def StreamMessages(self, request, context):
        """
        Handles server-streaming RPC for real-time message updates.
        When a client connects, it first sends all existing messages,
        then waits for new messages and streams them as they arrive.
        """
        print(f"Client connected for message streaming from {context.peer()}")
        for msg in list(_CHAT_MESSAGES):
            yield msg
        last_message_count = len(_CHAT_MESSAGES)
        while True:
            with _MESSAGE_CONDITION:
                _MESSAGE_CONDITION.wait(timeout=1)
                if not context.is_active():
                    print(f"Client from {context.peer()} disconnected from streaming.")
                    break
                while len(_CHAT_MESSAGES) > last_message_count:
                    new_message = _CHAT_MESSAGES[last_message_count]
                    yield new_message
                    last_message_count += 1
            time.sleep(0.01)
    # NEW: Implementation for GetMessageHistory
    def GetMessageHistory(self, request, context):
        """
        Handles unary RPC for getting a limited number of past messages.
        """
        print(f"Received request for message history with limit: {request.limit}")
        messages_to_send = []
        with _MESSAGE_CONDITION: # Acquire lock to ensure consistent read
            # Get the last 'limit' messages
            # Using list(deque) to get a slice, then reverse to get newest first if needed
            # For history, usually oldest first, so no reverse needed on deque slice
            start_index = max(0, len(_CHAT_MESSAGES) - request.limit)
            messages_to_send = list(_CHAT_MESSAGES)[start_index:]
        return chat_pb2.GetMessageHistoryResponse(messages=messages_to_send)
def serve():
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(
        ChatServiceServicer(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("gRPC Chat Server started on port 50051")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)
        print("gRPC Chat Server stopped.")
if __name__ == '__main__':
    serve()
