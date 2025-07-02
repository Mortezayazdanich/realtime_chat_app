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
        print(f"Received message: {request.message.sender}: {request.message.content}")
        with _MESSAGE_CONDITION:
            _CHAT_MESSAGES.append(request.message)
            _MESSAGE_CONDITION.notify_all()
        return chat_pb2.SendMessageResponse()
    def StreamMessages(self, request, context):
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
    # NEW: Implementation for DeleteMessage
    def DeleteMessage(self, request, context):
        """
        Handles unary RPC for deleting a message.
        (Simplified: In a real app, you'd delete by a unique ID from a database).
        For this example, we'll just log it.
        """
        print(f"Received request to delete message with ID: {request.message_id}")
        # In a real scenario, you'd interact with your database here
        # to find and remove the message.
        # For now, we'll simulate success.
        return chat_pb2.DeleteMessageResponse(success=True, message=f"Message {request.message_id} deleted (simulated).")
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
