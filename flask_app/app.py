# flask_app/app.py

from flask import Flask, render_template, request, Response, jsonify
import grpc
import time
import json
import threading
import queue
import os

# Import the generated gRPC and protobuf files
# Ensure these files (chat_pb2.py, chat_pb2_grpc.py) are in the same directory
# as app.py, or accessible via Python path.
# We'll adjust the import path if the generated files are in the parent directory
# or if we add a __init__.py to flask_app to make it a package.
# For simplicity, assuming they are directly accessible or copied.
try:
    import chat_pb2
    import chat_pb2_grpc
except ImportError:
    # If running from the flask_app directory, the generated files might be one level up
    # or in the chat_server directory. For this setup, we assume they are copied
    # or symlinked into flask_app for simplicity, or that the python path is set.
    # A more robust solution would involve proper package structure or sys.path manipulation.
    # For now, let's assume they are directly in flask_app or accessible.
    # If issues, ensure you've run the protoc command for flask_app.
    print("Warning: chat_pb2 or chat_pb2_grpc not found directly. Ensure protoc was run for flask_app directory.")
    # As a fallback for development, you might add:
    # import sys
    # sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'chat_server'))
    # import chat_pb2
    # import chat_pb2_grpc


app = Flask(__name__)

# gRPC server address
GRPC_SERVER_ADDRESS = 'localhost:50051'

# Queue to hold new messages received from the gRPC stream
# This queue will be consumed by the SSE endpoint
message_queue = queue.Queue()

# Thread to continuously stream messages from the gRPC server
def grpc_stream_consumer():
    """
    Connects to the gRPC server's StreamMessages RPC and
    puts received messages into a queue for the Flask SSE endpoint.
    """
    while True:
        try:
            with grpc.insecure_channel(GRPC_SERVER_ADDRESS) as channel:
                stub = chat_pb2_grpc.ChatServiceStub(channel)
                print("Connecting to gRPC server for streaming...")
                # The StreamMessages RPC returns an iterator
                for chat_message in stub.StreamMessages(chat_pb2.StreamMessagesRequest()):
                    # Put the received message into the queue
                    message_queue.put(chat_message)
                    # print(f"Queued message: {chat_message.sender}: {chat_message.content}")
        except grpc.RpcError as e:
            print(f"gRPC streaming error: {e}. Retrying in 5 seconds...")
            time.sleep(5) # Wait before retrying connection
        except Exception as e:
            print(f"Unexpected error in gRPC stream consumer: {e}. Retrying in 5 seconds...")
            time.sleep(5)

# Start the gRPC stream consumer in a separate thread when the app starts
# This ensures messages are continuously fetched in the background.
threading.Thread(target=grpc_stream_consumer, daemon=True).start()


@app.route('/')
def index():
    """
    Renders the main chat interface HTML page.
    """
    return render_template('index.html')

@app.route('/send_message', methods=['POST'])
def send_message():
    """
    Handles incoming POST requests to send a chat message.
    It acts as a gRPC client, sending the message to the gRPC server.
    """
    data = request.get_json()
    sender = data.get('sender', 'Anonymous')
    content = data.get('content', '')

    if not content:
        return jsonify({'status': 'error', 'message': 'Message content cannot be empty'}), 400

    try:
        with grpc.insecure_channel(GRPC_SERVER_ADDRESS) as channel:
            stub = chat_pb2_grpc.ChatServiceStub(channel)
            # Create a ChatMessage protobuf object
            chat_message = chat_pb2.ChatMessage(
                sender=sender,
                content=content,
                timestamp=int(time.time()) # Current Unix timestamp
            )
            # Create a SendMessageRequest and send it to the gRPC server
            request_pb = chat_pb2.SendMessageRequest(message=chat_message)
            stub.SendMessage(request_pb)
            return jsonify({'status': 'success', 'message': 'Message sent!'})
    except grpc.RpcError as e:
        print(f"gRPC error sending message: {e}")
        return jsonify({'status': 'error', 'message': f'Failed to send message: {e.details()}'}), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({'status': 'error', 'message': 'An unexpected error occurred.'}), 500

@app.route('/stream')
def stream_messages():
    """
    Server-Sent Events (SSE) endpoint to stream new chat messages to the browser.
    It continuously pulls messages from the message_queue and sends them.
    """
    def generate_messages():
        while True:
            try:
                # Get a message from the queue. block=True means it waits until a message is available.
                # timeout=1 ensures we don't block indefinitely and can check if the client disconnected.
                chat_message = message_queue.get(block=True, timeout=1)
                # Format the message as a JSON string and yield it as an SSE event
                data = {
                    'sender': chat_message.sender,
                    'content': chat_message.content,
                    'timestamp': chat_message.timestamp
                }
                yield f"data: {json.dumps(data)}\n\n"
            except queue.Empty:
                print("gRPC streaming error: {e}. Retrying in 5 seconds...")
                # No message in the queue, send a heartbeat to keep the connection alive
                # and allow the browser to detect if the server is still active.
                yield ":heartbeat\n\n"
            except Exception as e:
                print(f"Error in SSE stream: {e}")
                break # Break the loop if an error occurs

    # Set the content type for Server-Sent Events
    return Response(generate_messages(), mimetype='text/event-stream')

if __name__ == '__main__':
    # Run Flask app. In a production environment, use a WSGI server like Gunicorn.
    app.run(debug=True, port=5000)
