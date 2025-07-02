# chat_server/server_simple.py

import grpc
import time
import concurrent.futures
import threading
import collections
from datetime import datetime

# Import the generated gRPC and protobuf files
import chat_pb2
import chat_pb2_grpc

# In-memory storage for messages
messages_store = []
messages_lock = threading.Lock()

# Condition variable to notify streaming clients about new messages
_MESSAGE_CONDITION = threading.Condition()

# A dictionary to hold queues for each active streaming client
_CLIENT_QUEUES = collections.defaultdict(collections.deque)

class ChatServiceServicer(chat_pb2_grpc.ChatServiceServicer):
    """
    Simplified implementation of the gRPC ChatService using in-memory storage.
    """

    def SendMessage(self, request, context):
        """
        Handles unary RPC for sending a single message.
        Saves the message to in-memory storage.
        """
        with messages_lock:
            # Create message with current timestamp
            message_data = {
                "sender": request.message.sender,
                "content": request.message.content,
                "timestamp": int(time.time())
            }
            messages_store.append(message_data)
            print(f"Message stored: {message_data['sender']}: {message_data['content']}")
            
            # Create a ChatMessage object for broadcasting
            chat_message = chat_pb2.ChatMessage(
                sender=message_data["sender"],
                content=message_data["content"],
                timestamp=message_data["timestamp"]
            )
            
            # Add to all client queues
            for client_queue in _CLIENT_QUEUES.values():
                client_queue.append(chat_message)
            
            # Notify all waiting streams
            with _MESSAGE_CONDITION:
                _MESSAGE_CONDITION.notify_all()
        
        return chat_pb2.SendMessageResponse()

    def StreamMessages(self, request, context):
        """
        Handles server-streaming RPC for real-time message updates.
        Uses in-memory storage and threading for real-time updates.
        """
        client_id = context.peer()
        print(f"Client {client_id} connected for message streaming.")

        # Create a queue for this specific client
        client_queue = collections.deque()
        _CLIENT_QUEUES[client_id] = client_queue

        # Send existing messages first (last 10 messages)
        with messages_lock:
            recent_messages = messages_store[-10:] if len(messages_store) > 10 else messages_store
            for msg_data in recent_messages:
                chat_message = chat_pb2.ChatMessage(
                    sender=msg_data["sender"],
                    content=msg_data["content"],
                    timestamp=msg_data["timestamp"]
                )
                client_queue.append(chat_message)

        try:
            # Continuously yield messages from this client's queue as they arrive
            while context.is_active():
                try:
                    # Get a message from the queue
                    if client_queue:
                        msg = client_queue.popleft()
                        yield msg
                    else:
                        # Wait for a new message notification
                        with _MESSAGE_CONDITION:
                            _MESSAGE_CONDITION.wait(timeout=1)
                except Exception as e:
                    print(f"Error yielding message for client {client_id}: {e}")
                    break

        finally:
            # Clean up: remove the client's queue when the client disconnects
            if client_id in _CLIENT_QUEUES:
                del _CLIENT_QUEUES[client_id]
            print(f"Client {client_id} disconnected from streaming.")

    def GetMessageHistory(self, request, context):
        """
        Handles unary RPC for getting a limited number of past messages.
        """
        messages_to_send = []
        with messages_lock:
            # Get the latest 'limit' messages
            limit = min(request.limit, len(messages_store))
            recent_messages = messages_store[-limit:] if limit > 0 else []
            
            for msg_data in recent_messages:
                chat_message = chat_pb2.ChatMessage(
                    sender=msg_data["sender"],
                    content=msg_data["content"],
                    timestamp=msg_data["timestamp"]
                )
                messages_to_send.append(chat_message)
        
        return chat_pb2.GetMessageHistoryResponse(messages=messages_to_send)

    def DeleteMessage(self, request, context):
        """
        Handles unary RPC for deleting a message.
        For simplicity, delete by content match.
        """
        with messages_lock:
            original_length = len(messages_store)
            # Find and remove messages with matching content
            messages_store[:] = [msg for msg in messages_store if msg["content"] != request.message_id]
            deleted_count = original_length - len(messages_store)
            
            if deleted_count > 0:
                print(f"Deleted {deleted_count} message(s) with content '{request.message_id}'")
                return chat_pb2.DeleteMessageResponse(
                    success=True, 
                    message=f"Deleted {deleted_count} message(s) with content '{request.message_id}'"
                )
            else:
                return chat_pb2.DeleteMessageResponse(
                    success=False, 
                    message=f"No messages found with content '{request.message_id}'"
                )

def serve():
    """
    Starts the gRPC server.
    """
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(
        ChatServiceServicer(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("Simple gRPC Chat Server started on port 50051")
    try:
        while True:
            time.sleep(86400)  # Server runs for a day
    except KeyboardInterrupt:
        server.stop(0)
        print("Simple gRPC Chat Server stopped.")

if __name__ == '__main__':
    serve()
