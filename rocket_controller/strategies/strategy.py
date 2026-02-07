"""This module is responsible for defining the Strategy interface."""

from abc import ABC, abstractmethod
from datetime import datetime
import queue
from typing import Any, Dict, List, Tuple

from loguru import logger

from protos import packet_pb2, ripple_pb2
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)
from rocket_controller.helper import (
    MAX_U32,
    format_datetime,
    yaml_to_dict,
)
from rocket_controller.iteration_type import LedgerBasedIteration, TimeBasedIteration
from rocket_controller.network_manager import NetworkManager
from rocket_controller.validator_node_info import ValidatorNode
from rocket_controller.ws_subscriber import WSSubscriber
import threading
import socket
import time


class Strategy(ABC):
    """Class that defines the Strategy interface."""

    def __init__(
        self,
        network_config_path: str | None = None,
        strategy_config_path: str | None = None,
        auto_partition: bool = True,
        auto_parse_identical: bool = True,
        auto_parse_subsets: bool = True,
        keep_action_log: bool = True,
        iteration_type: TimeBasedIteration | None = None,
        network_overrides: Dict[str, Any] | None = None,
        strategy_overrides: Dict[str, Any] | None = None,
        log_dir: str | None = None,
        max_iteration: int | None = None,
        max_ledger_seq: int | None = None,
        grpc_port: int | None = None,
        instance_id: str | None = None,
    ):
        """
        Initialize the Strategy interface with necessary fields.

        Args:
            network_config_path (str, optional): The path of a network configuration file
            strategy_config_path (str, optional): The path of the strategy configuration file
            auto_partition (bool, optional): Whether the strategy will auto-apply network partitions.
            auto_parse_identical (bool, optional): Whether the strategy will perform same actions on identical messages.
            auto_parse_subsets (bool, optional): Whether the strategy will perform same actions on defined subsets.
            keep_action_log (bool, optional): Whether the strategy will keep an action log. Defaults to True.
            iteration_type (TimeBasedIteration, optional): Type of iteration logic to use.
            network_overrides (dict, optional): A dictionary containing parameter names and values which override the network config.
            strategy_overrides (dict, optional): A dictionary containing parameter names and values which override the strategy config.
        """
        if strategy_config_path is None:
            strategy_config_path = f"./config/default_{self.__class__.__name__}.yaml"
        if network_config_path is None:
            network_config_path = "./config/network/default_network.yaml"

        self.network = NetworkManager(
            auto_parse_identical=auto_parse_identical,
            auto_parse_subsets=auto_parse_subsets,
        )
        self.auto_partition: bool = auto_partition
        self.auto_parse_identical = auto_parse_identical
        self.auto_parse_subsets = auto_parse_subsets
        self.keep_action_log = keep_action_log
        self.network.network_config, self.params = self.init_configs(
            network_config_path, strategy_config_path
        )

        if network_overrides:
            for parameter_name in network_overrides:
                self.network.network_config[parameter_name] = network_overrides[
                    parameter_name
                ]
        if strategy_overrides:
            for parameter_name in strategy_overrides:
                # Special case for seed parameter (can be None in config)
                if parameter_name == "seed":
                    self.params[parameter_name] = int(strategy_overrides[parameter_name])
                else:
                    self.params[parameter_name] = type(self.params[parameter_name])(
                        strategy_overrides[parameter_name]
                    )

        logger.debug(f"Initialized final strategy parameters:" f"\n\t{self.params}")
        logger.debug(
            f"Initialized final strategy network configuration:"
            f"\n\t{self.network.network_config}"
        )

        self.start_datetime: datetime = datetime.now()
        self.log_dir = log_dir if log_dir is not None else self.start_datetime
        self.max_ledger_seq = max_ledger_seq if max_ledger_seq is not None else 10
        timeout_sec_per_seq = self.params.get("timeout_sec_per_seq", 30)
        self.instance_id = instance_id if instance_id is not None else ""
        self.iteration_type = (
            LedgerBasedIteration(
                max_iterations=max_iteration if max_iteration is not None else 10,
                max_ledger_seq=self.max_ledger_seq,
                ledger_timeout_seconds=self.max_ledger_seq*timeout_sec_per_seq,
                strategy_stopper=self.strategy_stopper,
                grpc_port=grpc_port,
                instance_id=instance_id,
            )
            if iteration_type is None
            else iteration_type
        )

        # Pass configured byzantine nodes (if any) to the iteration type so
        # spec checks can exclude them.
        self.byzz_nodes: list[int] = self.network.network_config.get("byzz_nodes", [])
        self.iteration_type.set_log_dir(
            self.log_dir, byzantine_node_ids=self.byzz_nodes
        )
        # a queue of subscriber pushed messages, producer-consumer pattern
        self._ws_event_queue: queue.Queue = queue.Queue()
        self._ws_consumer_thread = threading.Thread(target=self._ws_consumer, name="WSConsumer", daemon=True)
        self._ws_consumer_thread.start()
        self._save_validator_log_flag = threading.Event()

    def _ws_consumer(self) -> None:
        while True:
            if getattr(self, "_ws_subscriber", None) is None:
                time.sleep(1)
                continue
            if self._ws_subscriber.stop_event.is_set():
                break
            try:
                event = self._ws_event_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.update_status_subscribe(event)
            except Exception:
                logger.exception("ws consumer failed on event {}", event)

    @staticmethod
    def init_configs(
        network_config_path: str, strategy_config_path: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Initialize the strategy and network configuration from the given paths.

        Args:
            network_config_path: Path of the network config file.
            strategy_config_path: Path of the strategy config path.

        Returns:
            Tuple[Dict[str, Any], Dict[str, Any]]: Tuple containing the config files transformed to dictionaries.
        """
        params = yaml_to_dict(strategy_config_path)
        network_config = yaml_to_dict(network_config_path)
        return network_config, params

    def _subscriber_delayed_start(self, validator_nodes: List[ValidatorNode], max_wait: int = 30):
        # Try to connect to any validator WS port (public then admin) for up to max_wait seconds
        start_t = time.time()
        connected = []
        while time.time() - start_t < max_wait:
            if len(connected) == len(validator_nodes):
                logger.info(
                    "WSSubscriber: all websockets reachable, starting subscriber"
                )
                return

            connections = []
            for node in validator_nodes:
                wa = node.ws_private
                if (wa.host, wa.port) not in connected:
                    connections.append((wa.host, wa.port))

            for host, port in connections:
                try:
                    with socket.create_connection((host, port), timeout=1):
                        connected.append((host, port))
                        continue
                except Exception:
                    continue
            time.sleep(1)

        logger.info(
            "WSSubscriber: no websocket reachable within timeout. failed nodes: {} starting subscriber anyway".format(
                [
                    f"{n.ws_private.host}:{n.ws_private.port}"
                    for n in validator_nodes
                    if (n.ws_private.host, n.ws_private.port) not in connected
                ]
            )
        )

    def start_ws_subscriber(self, validator_node_list):
        # Start a background detector thread that will probe validator WS ports
        # and start the subscriber once detection completes (or times out).
        def _detector():
            try:
                # probe for up to 30s (this call is blocking but runs in detector thread)
                self._subscriber_delayed_start(validator_node_list, max_wait=30)
            except Exception:
                logger.exception("WS subscriber detector failed")
            finally:
                try:
                    # start() is non-blocking
                    self._ws_subscriber.start()
                    logger.info("WSSubscriber started by detector thread")
                except Exception:
                    logger.exception("Failed to start WSSubscriber after detection")

        t = threading.Thread(target=_detector, name="WSDetector", daemon=True)
        t.start()

    def update_network(self, validator_node_list: List[ValidatorNode]):
        """
        Update the strategy's attributes.

        Args:
            validator_node_list (list[ValidatorNode]): The list with (new) validator node information.
        """
        logger.info("Updating the strategy's network information")
        self.network.update_network(validator_node_list)
        self.iteration_type.set_validator_nodes(validator_node_list)
        self.setup()

        self._ws_subscriber = WSSubscriber(validator_node_list, log_dir=self.log_dir + f"iteration-{self.iteration_type.cur_iteration}", enqueue_func=self._ws_event_queue.put)
        self.start_ws_subscriber(validator_node_list)
        self._save_validator_log_flag.set()
        self._save_validator_log_background(validator_node_list)

        # setup iteration type's network reference
        self.iteration_type.set_network(self.network)

        

    def _save_validator_log_background(self, validator_node_list: List[ValidatorNode]):
        import os
        import subprocess
        instance_id = self.instance_id
        def _worker(node: ValidatorNode):
            out_dir = os.path.join("./logs/" + self.log_dir, f"iteration-{self.iteration_type.cur_iteration}", "validator_live_logs")
            container_name = node.get_container_name(instance_id)
            os.makedirs(out_dir, exist_ok=True)
            fname = f"validator_{node.id}_log"
            log_file_path = os.path.join(out_dir, fname + ".txt")
                
            while self._save_validator_log_flag.is_set():
                try:
                    with open(log_file_path, "w") as f:
                        try:
                            subprocess.run(['docker', 'logs', container_name], stdout=f, stderr=f, check=False, text=True)
                        except Exception as e:
                            logger.debug(f"_save_validator_log_async: docker logs failed for {container_name}: {e}")
                except Exception:
                    logger.exception(f"Failed to save validator log for node {node.id}")

                # Also periodically fetch the in-container debug logfile so we preserve debug logs
                debug_file_path = os.path.join(out_dir, f"validator_{node.id}_debug.txt")
                try:
                    with open(debug_file_path, "w") as df:
                        try:
                            subprocess.run([
                                'docker', 'exec', '-i', container_name,
                                'cat', '/var/log/rippled/debug.log'
                            ], stdout=df, stderr=df, check=False, text=True)
                        except Exception as e:
                            logger.debug(f"_save_validator_log_async: docker exec debug log failed for {container_name}: {e}")
                except Exception:
                    logger.exception(f"Failed to save validator debug log for node {node.id}")

                time.sleep(5)
        for node in validator_node_list:
            t = threading.Thread(target=_worker, args=(node,), name=f"ValidatorLogSaver-{node.id}", daemon=True)
            t.start()
        


    def strategy_stopper(self):
        self.stop_ws_subscriber()
        self._save_validator_log_flag.clear()

    def stop_ws_subscriber(self):
        if getattr(self, "_ws_subscriber", None):
            logger.info("Stopping WSSubscriber")
            self._ws_subscriber.stop()
            self._ws_subscriber = None

    def update_status(self, packet: packet_pb2.Packet):
        """
        Update the iteration's state variables, when a new TMStatusChange is received.

        Args:
            packet: The packet to check for a possible status update.
        """
        try:
            message, _ = PacketEncoderDecoder.decode_packet(packet)
            if isinstance(message, ripple_pb2.TMStatusChange):
                self.iteration_type.on_status_change(
                    message,
                    self.network.port_to_id(packet.from_port),
                    self.network.port_to_id(packet.to_port),
                    datetime.now() # TODO: use more acurate timestamp
                )
        except DecodingNotSupportedError:
            pass

    def update_status_subscribe(self, event: Any) -> None:
        """
        Update the status based on a websocket event.

        Args:
            event: The websocket event to process.
        """
        node_id, ev, timestamp = event.get("node_idx"), event.get("msg", {}), event.get("time")
        self.iteration_type.on_status_change_subscribe(from_id=node_id, message=ev, timestamp=timestamp)

    def process_packet(
        self,
        packet: packet_pb2.Packet,
    ) -> Tuple[bytes, int, int]:
        """
        Process an incoming packet, applies automatic processes if applicable.

        Args:
            packet: The packet to process.

        Returns:
            Tuple[bytes, int, int]: The processed packet as bytes, the action and the send amount.
        """
        peer_from_id = self.network.port_to_id(packet.from_port)
        peer_to_id = self.network.port_to_id(packet.to_port)

        # Check for identical previous messages or for identical messages within broadcasts.
        # This uses booleans to check whether the functionality has to be applied automatically.
        # First check whether we want to automatically parse re-sent messages,
        # then we check whether we want to perform identical actions for defined subsets of processes/peers.
        if (
            self.auto_parse_identical
            and (
                result := self.network.check_previous_message(
                    peer_from_id, peer_to_id, packet.data
                )
            )[0]
        ) or (
            self.auto_parse_subsets
            and (
                result := self.network.check_subsets(
                    peer_from_id, peer_to_id, packet.data
                )
            )[0]
        ):
            # If result[0] is True, then result[1] will contain usable data
            (final_data, action) = result[1]
            send_amount = 1

        # Handle the packet regularly
        else:
            # If no communication is allowed by partitions, then we drop immediately
            if self.auto_partition and not self.network.check_communication(
                peer_from_id, peer_to_id
            ):
                (final_data, action, send_amount) = (packet.data, MAX_U32, 1)
            else:
                (final_data, action, send_amount) = self.handle_packet(packet)

            # This is needed to keep track of previously sent messages
            if self.auto_parse_identical or self.auto_parse_subsets:
                self.network.set_message_action(
                    peer_from_id, peer_to_id, packet.data, final_data, action
                )

        self.update_status(packet)
        return final_data, action, send_amount

    @abstractmethod
    def setup(self):  # pragma: no cover
        """
        Setup method to be implemented by implementations of Strategy, not required.

        This method gets called at the end of update_network to initialize starting values.
        """
        pass

    @abstractmethod
    def handle_packet(
        self, packet: packet_pb2.Packet
    ) -> Tuple[bytes, int, int]:  # pragma: no cover
        """
        This method is responsible for returning a possibly mutated packet and an action.

        Args:
            packet: The original packet.

        Returns:
            Tuple[bytes, int]: The new packet, action and send amount..
        """
        pass
