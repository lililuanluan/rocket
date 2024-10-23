# Contributing to the Rocket Controller Module project

The document here aims to aid developers in understanding 
how to contribute to the controller module. Before making any changes 
follow the steps below in creating a sperate branch:

1. Create a new branch from `main`
2. Make your changes
3. Make sure the pipeline passes locally
4. Push your branch to the repository
5. Create a merge request to `main`

## The pipeline

- Unit testing using [pytest](https://docs.pytest.org/en/8.2.x/)
- Linting using [ruff](https://docs.astral.sh/ruff/)
- Type checking using [mypy](https://mypy.readthedocs.io/en/stable/)
- Style checking/formatting using [ruff](https://docs.astral.sh/ruff/)
- Automatic documentation generation using [Sphinx](https://www.sphinx-doc.org) and [Read-the-Docs](https://docs.readthedocs.io/en/stable/)

The pipeline can be replicated on your own machine 
by running the appropriate commands specified in `gitlab-ci.yml`

## Unit Testing & Static Analysis
To run the different pipeline stages, excluding the 
automatic documentation generation, [tox](https://tox.wiki/en/4.15.0/user_guide.html) is used.
It makes sure every stage of the pipeline runs in a 
separate environment, which eliminates interference. 
Another benefit of `tox` is the ability to execute the `tox` 
command in a local terminal, which will run unit testing, 
type checking, linting and style checking locally.
This means that your changes don't need to be pushed to GitLab to 
check whether the pipeline will fail or pass.

### Linux, Windows & macOS
```console
tox     # Run the pipeline locally (excluding documentation generation)
```

## Documentation Generation
The automated documentation generation will only run on a merge to main. After successful execution, it will publish the generated HTML on [GitLab Pages](https://docs.gitlab.com/ee/user/project/pages/) automatically, which means the most recent version of the documentation will always be available through our repository.

Below you can find how to generate documentation locally

### Linux
```console
cd docs
make clean && make html
```

### Windows
```console
PS > cd docs
PS > ./make.bat clean
PS > ./make.bat html
```

The documentation website files should now be in `docs/_build/html`. Then, inside this folder, you can open `index.html` with your browser to view the documentation locally.

## Protocol Buffers (gRPC)
If you want to make changes to a .proto file it is important that you make the exact same changes in the corresponding file in the interceptor repository and regenerate the necessary files both in the controller and interceptor.
- For the controller run:
```
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. protos/<filename.proto>
```


## Logging
Users are able to log custom columns to a csv file using the class `CSVLogger` in `csv_logger.py`, which will automatically open up a csv file using a filename, specified columns, and optional subdirectory.

### Action Logs
Action logs can be kept track of by using the `keep_log` boolean argument in the `__init__` method of `Strategy`. Users are able to set this boolean to true by calling `super.__init__` in classes that inherit from `Strategy`. When this argument is set to `True`,
an action log (csv) will be kept under the `logs/action_logs/[start_time]` directory along with a csv file containing the information of the validator nodes which were used during logging process.
This action log makes use of the `CSVLogger`'s child class `ActionLogger` which is dedicated to logging actions.
The log contains the timestamp when the action was taken on a packet, the action, sender peer port, receiver peer port, and the packet data as a hex string.

## Constructing New Strategies
To add a new strategy, you need to create a new file in the `strategies` folder with a class that inherits from the `Strategy` class. This class should implement the `handle_packet` method.
Every strategy should additionally implement the `setup` method to initialize starting values or to perform certain operations at start-up. When this method is not to be used, simply call `pass` in the method body, or leave the body empty.

### Configuration Files
Users are able to create new configuration files for strategies, these are categorized under network configurations and strategy parameter configurations.
The configurations have to be specified as yaml files, and will default to `default-strategy-config.yaml` and `default-network-config.yaml`.
The network configurations have to contain all fields which are also specified in the default file. Strategy parameter configurations can contain anything, as long as all fields are specified subsequently.
See `RandomFuzzer.yaml` for an example configuration. The configuration files to be used can be specified when calling `super.__init__` in the constructor classes of child classes of `Strategy`.
When no configuration files are given, or when `None` is given, then the Strategy will automatically fall back to the default configurations.
Strategy's parameters get placed in a dictionary, namely `self.params`. 

Example: A configuration file is used with one field `field1`. To access this field, `self.params['field1']` should be used.
Users are free to parse the dictionary into class attributes, this is not done automatically. Network configurations get communicated to the Network Packet Interceptor module automatically.
All configuration files must be in the `yaml` format.

### Network Partitions
Newly created `Strategy`'s should call `super().__init__()` to initialize needed fields to support network partitions.
Use `self.network.partition_network(partition: list[list[int]])` to partition the network using the validators' peer ID's in the partitions.
Example usage with a network of 3 nodes with peer ID's `0`, `1`, and `2` respectively where `0` will be isolated and `1` and `2` will be in the same partition: `self.network.partition_network([[0], [1, 2]])`.
The user can check the communication between 2 nodes manually by using
`self.network.check_communication(peer_from_id: int, peer_to_id: int)` which will return a boolean which indicates whether communication is possible between the 2 ports.
To create custom partitions, the functions `self.network.connect(peer_id_1, peer_id_2)` and `self.network.disconnect(peer_id_1, peer_id_2)` can be used.
The application will automatically drop messages sent between 2 nodes if communication is closed between those nodes.

### Identical Subsequent Messages
Every `Strategy` instance keeps track of previously sent messages sent between every node pair. In a network of `n` nodes, the stored information includes the `n+1` last sent message in bytes, the processed version of those last messages, and the actions that were taken on the messages.
The method `self.network.check_previous_message(peer_from_id: int, peer_to_id: int, message:bytes)` can be used which returns a tuple which also indicates whether one of the previous messages were identical to the current message.
In case that one of the previous messages were indeed identical, then the second entry of the tuple contains the processed version of the previous message and the action that was taken.
This functionality can be used to quickly perform the same actions on identical messages, which can be done automatically by setting the `auto_parse_identical` field in `Strategy`.
When `auto_parse_identical` is set to `False`, then the strategy will not keep track of any previously sent messages.
This functionality is useful when XRPL validator nodes resend messages to their peers, this functionality makes sure that those resends are automatically parsed so that the same actions will be taken on such messages.

### (Grouping) Broadcasts
Validator nodes often broadcast certain messages to all or a subset of peers. The `Strategy` interface has built-int functionality to perform identical actions on all messages sent within such broadcasts.
Use the `auto_parse_subsets` boolean to activate this functionality, this defaults to `True`. Use `network.set_subsets_dict` to set a new formation of peer-subsets combinations. Use `network.set_subsets_dict_entry` to modify single entries.
Example: we have 5 nodes, with respective id's 0, 1, 2, 3, 4. We want to make sure that identical actions will be taken on broadcasts that get sent from node 1 to node 0 and node 2. Moreover, we want to perform the same actions on broadcasts from node 1 to node 3 and 4. To achieve this, we call
`self.network.set_subsets_dict({1: [[0, 2], [3, 4]]})`. If we would not want to do this for the subset `[3, 4]`, then we could simply call `self.network.set_subsets_dict({1: [0, 2])` without specifying a 2-dimensional list, but rather specifying a linear list.
The parsing happens automatically by the controller, users do not have to perform manual applications of such defined subsets.

