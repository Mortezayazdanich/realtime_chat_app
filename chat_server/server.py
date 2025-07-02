# chat_server/server.py

import grpc
import time
import concurrent.futures
import threading
import collections

# Import the generated gRPC and protobuf files
# Ensure these files (chat_pb2.py, chat_pb2_grpc.py) are in the same directory
# as server.py, or accessible via Python path.
import chat_pb2
import chat_pb2_grpc

# In-memory storage for chat messages.
# In a real application, this would be a database (e.g., PostgreSQL, MongoDB).
# We'll use a deque for efficient appending and popping from both ends,
# though for this simple case, a list is also fine.
_CHAT_MESSAGES = collections.deque(maxlen=100) # Store last 100 messages

# Condition variable to notify streaming clients about new messages.
# When a new message arrives, we acquire the lock, append the message,
# and then notify all waiting clients.
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
            # Add the new message to our message store
            _CHAT_MESSAGES.append(request.message)
            # Notify all clients waiting on the condition that a new message is available
            _MESSAGE_CONDITION.notify_all()
        return chat_pb2.SendMessageResponse()

    def StreamMessages(self, request, context):
        """
        Handles server-streaming RPC for real-time message updates.
        When a client connects, it first sends all existing messages,
        then waits for new messages and streams them as they arrive.
        """
        print(f"Client connected for message streaming from {context.peer()}")

        # Send existing messages to the newly connected client
        for msg in list(_CHAT_MESSAGES): # Iterate over a copy to avoid issues if _CHAT_MESSAGES changes
            yield msg

        # Now, continuously wait for new messages and stream them
        # This loop will run as long as the client connection is active.
        last_message_count = len(_CHAT_MESSAGES)
        while True:
            with _MESSAGE_CONDITION:
                # Wait until notified that a new message has arrived,
                # or if the client disconnects (context.is_active becomes False).
                # The timeout ensures we periodically check context.is_active.
                _MESSAGE_CONDITION.wait(timeout=1) # Wait for 1 second, then re-check

                # If the client has disconnected, break the loop
                if not context.is_active():
                    print(f"Client from {context.peer()} disconnected from streaming.")
                    break

                # If new messages have arrived, send them to the client
                while len(_CHAT_MESSAGES) > last_message_count:
                    new_message = _CHAT_MESSAGES[last_message_count]
                    yield new_message
                    last_message_count += 1
            # Small sleep to prevent busy-waiting if no new messages and context.is_active() is true
            time.sleep(0.01)


def serve():
    """
    Starts the gRPC server.
    """
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(
        ChatServiceServicer(), server)
    server.add_insecure_port('[::]:50051') # Listen on all interfaces, port 50051
    server.start()
    print("gRPC Chat Server started on port 50051")
    try:
        while True:
            time.sleep(86400) # Server runs for a day
    except KeyboardInterrupt:
        server.stop(0)
        print("gRPC Chat Server stopped.")

if __name__ == '__main__':
    serve()
