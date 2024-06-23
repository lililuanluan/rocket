How to do Message Mutation
==========================

The first step of mutating messages, is creating a new strategy in the :code:`xrpl_controller/strategies` folder. For
the sake of this tutorial, we will name this strategy :code:`mutation_example.py`.

For setting up the class, copy the following code in your newly created strategy.

.. code-block:: python

    from datetime import datetime
    from typing import Tuple

    from xrpl.utils import datetime_to_ripple_time

    from protos import packet_pb2, ripple_pb2
    from xrpl_controller.iteration_type import IterationType
    from xrpl_controller.strategies.encoder_decoder import (
        DecodingNotSupportedError,
        PacketEncoderDecoder,
    )
    from xrpl_controller.strategies.strategy import Strategy


    class MutationExample(Strategy):
        """Class that shows a basic example of message mutation."""

        def __init__(self, iteration_type: IterationType | None = None):
            """Initialize the Strategy parent class."""
            super().__init__(iteration_type=iteration_type)

        def setup(self):
            """This setup method is called after the network of validator nodes is initialized."""
            pass

        def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
            """This method is called for every single network message intercepted in the network."""
            pass

To start the mutation process, we need to deserialize the :code:`packet.data` to a Python object. Thankfully, there are
utility methods for this purpose defined in the :code:`PacketEncoderDecoder` class.

Modify the :code:`handle_packet` method as follows:

.. code-block:: python

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
        try:
            message, message_type_no = PacketEncoderDecoder.decode_packet(packet)
        except DecodingNotSupportedError:
            return packet.data, 0

The first part of the snippet calls the :code:`decode_packet` method, which deserializes the raw packet data (bytes),
and yields an initialized Python class which corresponds to the message as defined in the :code:`ripple` Protocol
Buffers. The deserialized message is stored in the :code:`message` variable, the detected message type number is
stored in the :code:`message_type_no` variable.

If decoding a message type is not supported, e.g. due to a newly introduced message type in an update of the ripple
daemon software, it is important to handle the error, and in this case return the original bytes back to the network.

Now that the message is deserialized, we can start mutating it. For this tutorial, we will mutate the TMProposeSet
message type. Before we can start mutation, we thus have to check whether the returned class is a TMProposeSet
instance.

.. code-block:: python

    if not isinstance(message, ripple_pb2.TMProposeSet):
        return packet.data, 0

If the message is not an instance of the TMProposeSet message type, we return the data without applying any mutations.

Now that we know that the message is of type TMProposeSet, we can do a simple mutation.

.. code-block:: python

    message.closeTime = datetime_to_ripple_time(datetime.now())

Since :code:`closeTime` is a field of a TMProposeSet message, mutation is as simple as doing a direct assignment
operation. However, the TMProposeSet message requires a :code:`secp256k1` signature. This means when the message is
mutated, the original signature becomes invalid, and thus the message has to be signed again. To make this as easy as
possible, we have created a utility method for this.

.. code-block:: python

    signed_message = PacketEncoderDecoder.sign_message(
        message,
        self.network.public_to_private_key_map[message.nodePubKey.hex()],
    )

This method signs the message with the private key corresponding to the public key defined in the original message.
The signed message is returned.

The last step to complete the mutation, is serializing the message to its binary form. To do this, we have provided
a utility method.

.. code-block:: python

    return PacketEncoderDecoder.encode_message(signed_message, message_type_no), 0

After completing all of these steps, you can verify you did everything correctly by comparing your file with the
provided :code:`xrpl_controller/strategies/mutation_example.py` file.