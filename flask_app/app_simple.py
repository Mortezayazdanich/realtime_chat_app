# flask_app/app_simple.py

from flask import Flask, render_template, request, Response, jsonify
import grpc
import time
import json
import threading
import queue
import os

# Import the generated gRPC and protobuf files
import chat_pb2
import chat_pb2_grpc

app = Flask(__name__)

# gRPC server address
GRPC_SERVER_ADDRESS = 'localhost:50051'

# Queue to hold new messages received from the gRPC stream
message_queue = queue.Queue()

# Flag to control the gRPC streaming thread
streaming_active = threading.Event()
streaming_active.set()

def grpc_stream_consumer():
    """
    Connects to the gRPC server's StreamMessages RPC and
    puts received messages into a queue for the Flask SSE endpoint.
    """
    while streaming_active.is_set():
        try:
            print("Attempting to connect to gRPC server...")
            with grpc.insecure_channel(GRPC_SERVER_ADDRESS) as channel:
                # Add a shorter timeout for connection
                grpc.channel_ready_future(channel).result(timeout=5)
                
                stub = chat_pb2_grpc.ChatServiceStub(channel)
                print("Connected to gRPC server for streaming")
                
                # The StreamMessages RPC returns an iterator
                for chat_message in stub.StreamMessages(chat_pb2.StreamMessagesRequest()):
                    if not streaming_active.is_set():
                        break
                    message_queue.put(chat_message)
                    
        except grpc.FutureTimeoutError:
            print("gRPC connection timeout. Retrying in 5 seconds...")
            time.sleep(5)
        except grpc.RpcError as e:
            print(f"gRPC streaming error: {e}. Retrying in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"Unexpected error in gRPC stream consumer: {e}. Retrying in 5 seconds...")
            time.sleep(5)

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
    """
    data = request.get_json()
    sender = data.get('sender', 'Anonymous')
    content = data.get('content', '')

    if not content:
        return jsonify({'status': 'error', 'message': 'Message content cannot be empty'}), 400

    try:
        with grpc.insecure_channel(GRPC_SERVER_ADDRESS) as channel:
            # Add timeout for connection
            grpc.channel_ready_future(channel).result(timeout=5)
            
            stub = chat_pb2_grpc.ChatServiceStub(channel)
            chat_message = chat_pb2.ChatMessage(
                sender=sender,
                content=content,
                timestamp=int(time.time())
            )
            request_pb = chat_pb2.SendMessageRequest(message=chat_message)
            stub.SendMessage(request_pb)
            return jsonify({'status': 'success', 'message': 'Message sent!'})
            
    except grpc.FutureTimeoutError:
        return jsonify({'status': 'error', 'message': 'Connection timeout to chat server'}), 500
    except grpc.RpcError as e:
        print(f"gRPC error sending message: {e}")
        return jsonify({'status': 'error', 'message': f'Failed to send message: {e.details()}'}), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({'status': 'error', 'message': 'An unexpected error occurred.'}), 500

@app.route('/stream')
def stream_messages():
    """
    Server-Sent Events (SSE) endpoint to stream new chat messages.
    """
    def generate_messages():
        while True:
            try:
                chat_message = message_queue.get(block=True, timeout=1)
                data = {
                    'sender': chat_message.sender,
                    'content': chat_message.content,
                    'timestamp': chat_message.timestamp
                }
                yield f"data: {json.dumps(data)}\n\n"
            except queue.Empty:
                # Send heartbeat
                yield ":heartbeat\n\n"
            except Exception as e:
                print(f"Error in SSE stream: {e}")
                break

    return Response(generate_messages(), mimetype='text/event-stream')

@app.route('/health')
def health():
    """Simple health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'Flask app is running'})

if __name__ == '__main__':
    # Start the gRPC stream consumer in a separate thread
    print("Starting gRPC stream consumer thread...")
    stream_thread = threading.Thread(target=grpc_stream_consumer, daemon=True)
    stream_thread.start()
    
    try:
        # Run Flask app
        print("Starting Flask app on port 5001...")
        app.run(debug=True, port=5001, use_reloader=False)  # Disable reloader to avoid threading issues
    finally:
        # Clean shutdown
        streaming_active.clear()
        print("Flask app shut down")
