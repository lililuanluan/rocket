from concurrent import futures

import grpc
from protos import packet_pb2, packet_pb2_grpc
from xrpl_controller import controller


class PacketService(packet_pb2_grpc.PacketServiceServicer):
    def SendPacket(self, request, context):
        # Pass intercepted packet to controller
        controller.handle_packet(request.data)
        return packet_pb2.PacketAck(message="Packet received successfully")

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    packet_pb2_grpc.add_PacketServiceServicer_to_server(PacketService(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
