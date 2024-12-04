# Rocket's controller module

Rocket is an easy-to-use and extendable system-level testing framework 
for the XRP Ledger Consensus Algorithm.

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

Configuration files for Rocket are found in the [config](config) subdirectory, which 
includes a default network configuration file as well as a default configuration
file for every fuzzing strategy available to the tool.

#### Network configuration

To change the network configuration, you can edit the 
`config/network/default_network.yaml` file. Alternatively, 
you can create a new file and pass its relative path to the tool using 
the `--network_config` flag.

Documentation on the various configuration options are included in the default
configuration file. 
Overriding certain network configuration parameters is possible through the
following CLI options:
- `--nodes AMOUNT` will override the amount of nodes to start to `AMOUNT` (int)
- `--partition PARTITION` will override the network partition to use to 
  the specified `PARTITION` (str) with format specified in the
  `config/network/default_network.yaml` file. (e.g. `[[0,1,2]]` or `[[0,1],[1,2]]`)
- `--nodes_unl UNL` will override the node's UNLs (Unique Node List, i.e. trusted nodes) to 
  the specified `UNL` (str) with format specified in the
  `config/network/default_network.yaml` file. (e.g. `[[0,1,2],[1,0,2],[2,0,1]]` or `[[0,1],[1,2]]`)

Note: If any of your expressions for `PARTITION` or `UNL` contain spaces, make sure you
surround your expression with double quotes: `"[[0, 1, 2], [1, 0, 2], [2, 0, 1]]"`

#### Strategy configuration
To change a specific strategy's configurable parameters (e.g. RandomFuzzer)
you can edit the `config/default_RandomFuzzer.yaml` file. Alternatively, 
you can create a new YAML file and pass its relative path to the CLI using 
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

For the full list of CLI options, run the following command:

```bash
python3 -m xrpl_controller -h
```

## Creating a new Strategy

Rocket's design allows for easy creation of new fuzzing strategies. Below are
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

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        # Simplest case, return the packet immediately, with no delay and no duplicate.
        # 
        # This method is called for EVERY message that is transmitted between the XRPL validator nodes.
        # The return format is (bytes: Message Bytes, int: Delay in ms, int: Amount of duplicates to send)
        # 
        # The delay can to be set to the max unsigned integer value to simulate a drop, 
        # any other value for delay (in ms), and 0 for direct send. 
        # The duplicate amount signifies how many times the message will be sent.
        # The below return statement sends the original message data without any delays, 
        # once on the network (no duplicates).
        return packet.data, 0, 1
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
from xrpl_controller.strategies.strategy import Strategy

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

### Additional notes

The quickstart only covers the basic functionality. If you want to know more about how to implement
message mutation, take a look at the `xrpl_controller/strategies/mutation_example.py` file.

## Changing test iteration logic

After defining a strategy and running it, you will see that, by default,
a test strategy executed by Rocket runs for a total of 10 iterations, with 
each iteration validating exactly 5 ledgers. 
This is the `LedgerBasedIteration` type. You can change its parameters by 
overriding the `iteration_type` parameter while initializing the `Strategy` 
superclass from your created strategy.

```python
from xrpl_controller.strategies.strategy import Strategy
from xrpl_controller.iteration_type import LedgerBasedIteration

class ExampleStrategy(Strategy):
    def __init__(self):
        super().__init__(
          iteration_type=LedgerBasedIteration(max_iterations=10, max_ledger_seq=5)
        )
```

Running 10 Rocket test iterations with a fixed time of 60 seconds per iteration
is done as follows using `TimeBasedIteration`:

```python
from xrpl_controller.strategies.strategy import Strategy
from xrpl_controller.iteration_type import TimeBasedIteration

class ExampleStrategy(Strategy):
    def __init__(self):
        super().__init__(
          iteration_type=TimeBasedIteration(max_iterations=10, timeout_seconds=60)
        )
```

If these two possible iteration types do not cater for your strategy's needs,
you can create your own custom iteration type in [xrpl_controller/iteration_type.py](xrpl_controller/iteration_type.py).

Note: Make sure your iteration type inherits from `TimeBasedIteration`.

# Analysing the performance of the consensus algorithm

After running your test cases, you can analyse the performance of the consensus algorithm. Several logs are created in the `logs/{start_time}` directory. 
The most important log is the `aggregated_spec_check_log.json` file. This file contains the aggregated results of the spec checks that were performed during the test.
- If all iterations were "correct_runs" or "timeout_before_startup", the consensus algorithm behaved as expected.
- If any iteration was "error", "failed_termination" or "failed_agreement", the consensus algorithm did not behave as expected, and you should inspect the corresponding iteration logs in the `logs/{start_time}/iteration-{number}` directory.

Good luck protecting the XRP Ledger!

## Useful Resources

- To contribute to the controller module read: 
[CONTRIBUTING.md](CONTRIBUTING.md)
- To run tests read:
[TESTING.md](TESTING.md)


