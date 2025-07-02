# chat_server/server.py

import grpc
import time
import concurrent.futures
import threading
import collections
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore, auth

# Import the generated gRPC and protobuf files
import chat_pb2
import chat_pb2_grpc

# Global variables provided by the Canvas environment for Firebase
# These will be populated at runtime.
# Use os.environ.get to safely access environment variables
app_id = os.environ.get('__app_id', 'default-app-id')
firebase_config_str = os.environ.get('__firebase_config', '{}')
initial_auth_token = os.environ.get('__initial_auth_token', None)

db = None # Firestore client
auth_client = None # Firebase Auth client

# Condition variable to notify streaming clients about new messages.
# This is still used for immediate notification within the server process,
# but Firestore's on_snapshot is the primary real-time mechanism.
_MESSAGE_CONDITION = threading.Condition()

# A dictionary to hold queues for each active streaming client
# This allows us to push new messages to specific clients from Firestore snapshots.
_CLIENT_QUEUES = collections.defaultdict(collections.deque)

# Firestore collection path for public chat messages
# Using __app_id to ensure unique collections per Canvas app instance
PUBLIC_CHAT_COLLECTION = f"artifacts/{app_id}/public/data/chat_messages"

def initialize_firebase():
    """Initializes Firebase Admin SDK."""
    global db, auth_client

    # Check if Firebase is already initialized to prevent re-initialization errors
    if firebase_admin._apps:
        print("Firebase already initialized.")
        db = firestore.client()
        auth_client = auth.Client(firebase_admin.get_app())
        return

    try:
        firebase_config = {}
        print(f"DEBUG: Raw __firebase_config_str: {firebase_config_str}") # DEBUG PRINT

        if firebase_config_str:
            try:
                firebase_config = json.loads(firebase_config_str)
            except json.JSONDecodeError:
                print("Warning: __firebase_config is not a valid JSON string. Attempting default initialization.")
        
        print(f"DEBUG: Parsed firebase_config: {firebase_config}") # DEBUG PRINT

        # Attempt to initialize with service account credentials if valid config is provided
        if firebase_config and firebase_config.get("type") == "service_account":
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)
            print("Firebase initialized using service account credentials.")
        else:
            # Fallback to default credentials (e.g., when running in a Google Cloud environment
            # with Application Default Credentials set up, or if the service account JSON is invalid).
            print("Attempting Firebase initialization with default credentials (no valid service account JSON provided).")
            firebase_admin.initialize_app()

        db = firestore.client()
        auth_client = auth.Client(firebase_admin.get_app())
        print("Firestore client and Auth client initialized.")

    except Exception as e:
        print(f"Critical Error initializing Firebase: {e}")
        # If initialization fails, db and auth_client will remain None,
        # and subsequent database operations will correctly report "Database not ready."
        pass


class ChatServiceServicer(chat_pb2_grpc.ChatServiceServicer):
    """
    Implements the gRPC ChatService.
    Handles sending, streaming, getting history, and deleting chat messages
    with Firestore as the backend.
    """

    def SendMessage(self, request, context):
        """
        Handles unary RPC for sending a single message.
        Saves the message to Firestore.
        """
        if not db:
            print("Firestore not initialized. Cannot send message.")
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Database not ready.")
            return chat_pb2.SendMessageResponse()

        message_data = {
            "sender": request.message.sender,
            "content": request.message.content,
            "timestamp": firestore.SERVER_TIMESTAMP # Use server timestamp for accuracy
        }
        try:
            # Add message to Firestore. doc_ref is a tuple (update_time, DocumentReference)
            doc_ref = db.collection(PUBLIC_CHAT_COLLECTION).add(message_data)
            print(f"Message saved to Firestore with ID: {doc_ref[1].id}")

            # Note: The actual message with server timestamp will be streamed back
            # by the StreamMessages listener. We don't need to manually notify here
            # for the in-memory queue as Firestore's on_snapshot handles propagation.
            return chat_pb2.SendMessageResponse()
        except Exception as e:
            print(f"Error saving message to Firestore: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Failed to save message: {e}")
            return chat_pb2.SendMessageResponse()

    def StreamMessages(self, request, context):
        """
        Handles server-streaming RPC for real-time message updates from Firestore.
        Uses Firestore's on_snapshot listener to stream new messages.
        """
        if not db:
            print("Firestore not initialized. Cannot stream messages.")
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Database not ready.")
            return

        client_id = context.peer()
        print(f"Client {client_id} connected for message streaming.")

        # Create a queue for this specific client
        client_queue = collections.deque()
        _CLIENT_QUEUES[client_id] = client_queue

        # Callback for Firestore snapshot listener
        def on_snapshot(col_snapshot, changes, read_time):
            """
            This callback is executed whenever there's a change in the collection.
            It processes new messages and adds them to the client's queue.
            """
            for change in changes:
                if change.type.name == 'ADDED':
                    doc_data = change.document.to_dict()
                    # Convert Firestore Timestamp object to Unix timestamp (int)
                    timestamp = doc_data.get('timestamp')
                    if hasattr(timestamp, 'timestamp'): # Check if it's a Firestore Timestamp object
                        timestamp = int(timestamp.timestamp())
                    else: # Fallback if for some reason it's not a Timestamp object
                        timestamp = int(time.time()) if timestamp is None else int(timestamp)

                    chat_message = chat_pb2.ChatMessage(
                        sender=doc_data.get('sender', 'Unknown'),
                        content=doc_data.get('content', ''),
                        timestamp=timestamp
                    )
                    # Put the new message into this client's queue
                    client_queue.append(chat_message)
                    # Notify the waiting loop for this client that a new message is available
                    with _MESSAGE_CONDITION:
                        _MESSAGE_CONDITION.notify_all()

        # Start listening to Firestore changes.
        # Order by timestamp and limit to last 100 for initial sync.
        query_ref = db.collection(PUBLIC_CHAT_COLLECTION).order_by('timestamp').limit_to_last(100)
        query_watcher = query_ref.on_snapshot(on_snapshot)

        try:
            # Continuously yield messages from this client's queue as they arrive
            while context.is_active():
                try:
                    # Get a message from the queue. block=True waits until a message is available.
                    # timeout=1 ensures we periodically check context.is_active() and prevent indefinite blocking.
                    msg = client_queue.popleft() # Pop from the left (oldest message)
                    yield msg
                except IndexError:
                    # Queue is empty, wait for a new message notification
                    with _MESSAGE_CONDITION:
                        _MESSAGE_CONDITION.wait(timeout=1) # Wait for 1 second, then re-check context status
                except Exception as e:
                    print(f"Error yielding message for client {client_id}: {e}")
                    break # Break the loop if an unrecoverable error occurs in yielding

        finally:
            # Clean up: remove the Firestore listener and the client's queue when the client disconnects
            query_watcher.unsubscribe()
            if client_id in _CLIENT_QUEUES:
                del _CLIENT_QUEUES[client_id]
            print(f"Client {client_id} disconnected from streaming. Firestore listener unsubscribed.")


    def GetMessageHistory(self, request, context):
        """
        Handles unary RPC for getting a limited number of past messages from Firestore.
        """
        if not db:
            print("Firestore not initialized. Cannot get message history.")
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Database not ready.")
            return chat_pb2.GetMessageHistoryResponse()

        messages_to_send = []
        try:
            # Query Firestore for the latest 'limit' messages, ordered by timestamp descending
            query = db.collection(PUBLIC_CHAT_COLLECTION).order_by('timestamp', direction=firestore.Query.DESCENDING).limit(request.limit)
            docs = query.stream() # Get documents as a stream

            for doc in docs:
                doc_data = doc.to_dict()
                timestamp = doc_data.get('timestamp')
                if hasattr(timestamp, 'timestamp'): # If it's a Firestore Timestamp object
                    timestamp = int(timestamp.timestamp())
                else:
                    timestamp = int(timestamp) if timestamp is not None else int(time.time())

                chat_message = chat_pb2.ChatMessage(
                    sender=doc_data.get('sender', 'Unknown'),
                    content=doc_data.get('content', ''),
                    timestamp=timestamp
                )
                messages_to_send.append(chat_message)

            # Reverse the list to have oldest messages first, which is typical for history display
            messages_to_send.reverse()
            return chat_pb2.GetMessageHistoryResponse(messages=messages_to_send)
        except Exception as e:
            print(f"Error fetching message history from Firestore: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Failed to fetch message history: {e}")
            return chat_pb2.GetMessageHistoryResponse()


    def DeleteMessage(self, request, context):
        """
        Handles unary RPC for deleting a message from Firestore.
        (Requires a message_id, which in a real app would be the Firestore document ID).
        For this example, we'll simulate deletion by content match.
        """
        if not db:
            print("Firestore not initialized. Cannot delete message.")
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Database not ready.")
            return chat_pb2.DeleteMessageResponse(success=False, message="Database not ready.")

        print(f"Received request to delete message with ID (content match): {request.message_id}")
        try:
            # In a real system, you would pass the actual Firestore document ID from the client
            # and use doc_ref = db.collection(...).document(request.message_id) followed by doc_ref.delete().
            # For this simplified example, we'll try to find a message by content and delete the first match.
            # This is NOT efficient or robust for real deletion.
            query_to_delete = db.collection(PUBLIC_CHAT_COLLECTION).where('content', '==', request.message_id).limit(1)
            docs_to_delete = query_to_delete.stream()

            deleted_count = 0
            for doc in docs_to_delete:
                doc.reference.delete()
                deleted_count += 1
                print(f"Deleted message with content '{request.message_id}' (Firestore ID: {doc.id})")
                break # Delete only the first match for this simple example

            if deleted_count > 0:
                return chat_pb2.DeleteMessageResponse(success=True, message=f"Message '{request.message_id}' deleted (simulated by content match).")
            else:
                return chat_pb2.DeleteMessageResponse(success=False, message=f"Message '{request.message_id}' not found for deletion by content.")

        except Exception as e:
            print(f"Error deleting message from Firestore: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Failed to delete message: {e}")
            return chat_pb2.DeleteMessageResponse(success=False, message=f"Failed to delete message: {e}")


def serve():
    """
    Starts the gRPC server and initializes Firebase.
    """
    initialize_firebase() # Initialize Firebase before starting the server

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
