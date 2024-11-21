# Rocket's controller module

This module is the main part of Rocket and is responsible for 
mutating the messages that have been intercepted from 
the [packet-interceptor](https://gitlab.ewi.tudelft.nl/cse2000-software-project/2023-2024/cluster-q/13d/xrpl-packet-interceptor)
as well as determining a network action for each message. 
The interceptor is run as a subprocess from the controller.

## Quickstart

### Pre-Requisites

- Python 3.12+
- Docker engine (Docker Desktop for Windows)
- All packages in `requirements.txt`
- A compiled binary of the [packet-interceptor](https://gitlab.ewi.tudelft.nl/cse2000-software-project/2023-2024/cluster-q/13d/xrpl-packet-interceptor)

```bash
pip install -r requirements.txt
```

### Configuration

Configuration files for Rocket are found in the `config` subdirectory, which 
includes a default network configuration file as well as a default configuration
file for every fuzzing strategy available to the tool.

#### Network configuration

To change the network configuration, you can edit the 
`config/network/default_network.yaml` file. Alternatively, 
create a new file and pass its relative path to the tool using 
the `--network_config` flag.

Documentation on the various configuration options are included in the default
configuration file. 
Overriding certain network configuration parameters is possible through the
following CLI options:
- `--nodes AMOUNT` will override the amount of nodes to start to `AMOUNT` (int)
- `--partition PARTITION` will override the network partition to use to 
  the specified `PARTITION` (str) with format specified in the
  `config/network/default_network.yaml` file. (e.g. `[[1,2,3]]` or `[[1,2], [2,3]]`)

#### Strategy configuration
To change a specific strategy's configurable parameters (e.g. RandomFuzzer)
you can edit the `config/default_RandomFuzzer.yaml` file. Alternatively, 
create a new yaml file and pass its relative path to the CLI using 
the `--config` option.

Overriding strategy parameters is also possible through the CLI using 
the `--overrides` option. The format of these overrides is
`PARAM1=VALUE1,PARAM2=VALUE2`. Note that the parameters specified in the 
overrides need to be present in the corresponding strategy's configuration file.

### Running

Below is a basic example of running the tool with default settings, using
the included RandomFuzzer as the fuzzing strategy.

```bash
python3 -m xrpl_controller RandomFuzzer
```

The full list of CLI options can be viewed using the command below.

```bash
python3 -m xrpl_controller -h
```

## Creating a new Strategy

Rocket's design allows for easy addition of new fuzzing strategies. Below are
the steps needed to implement and use your new strategy.

### Creating the Strategy files

To create your Strategy, create a new file as follows:
`xrpl_controller/strategies/example_strategy.py`.

To initialize the strategy, add the following code to your newly
created Strategy file.

```python
from typing import Tuple
from protos import packet_pb2
from xrpl_controller.strategies.strategy import Strategy


class ExampleStrategy(Strategy):
    def __init__(
        self,
        # Add any parent class (Strategy) parameters you want to be able to override here.
    ):
        super().__init__(
            # Override default parent class (Strategy) parameters here
        )

    def setup(self):
        # Any setup logic can be added here, this method is called after the testing network is fully set up.
        pass

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
        # Simplest case, return the packet immediately, with no delay.
        # This method is called for EVERY message that is transmitted between the XRPL validator nodes.
        return packet.data, 0
```

If you do not need configurable parameters, then this is it! You have successfully
added a new strategy to Rocket, and you can now use it as follows:

```bash
python -m xrpl_controller ExampleStrategy
```

Note: In the previous command, `ExampleStrategy` is the exact name of the created class.

### Adding configurable parameters

If you are planning to run large batches of tests with your new strategy,
it can be useful to extract important parameters to a configuration file. 
When running your Strategy for the first time using default settings 
(`python -m xrpl_controller ExampleStrategy`), an empty configuration file is
automatically created at `config/default_ExampleStrategy.yaml`. If not, you can
create it manually. As an example, we will create and implement a 
custom parameter for the `ExampleStrategy` class created above.

To start, open `config/default_ExampleStrategy.yaml`, and add your parameters to
the file.

```yaml
# config/default_ExampleStrategy.yaml
foo: bar
```

That's it! The parameter can now be accessed from anywhere in the ExampleStrategy:

```python
class ExampleStrategy(Strategy):
    def some_method(self):
        print(self.params["foo"]) # prints 'bar'
```

(Note: The **default** configuration filename MUST follow the following format: 
`default_<CLASSNAME>.yaml`)

In case you want to use different/multiple configuration files,
simply pass its relative path to the CLI with the `--config` option.

Example:
```yaml
# my_config_dir/config_1.yaml
foo: bar baz
```

```bash
python -m xrpl_controller ExampleStrategy --config my_config_dir/config_1.yaml
```

## Useful Resources

- To contribute to the controller module read: 
[CONTRIBUTING.md](CONTRIBUTING.md)
- To run tests read:
[TESTING.md](TESTING.md)


