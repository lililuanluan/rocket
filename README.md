# XRPL controller module

## Getting Started
See the related repository [xrpl-packet-interceptor](https://gitlab.ewi.tudelft.nl/cse2000-software-project/2023-2024/cluster-q/13d/xrpl-packet-interceptor) for the interceptor module.

### Pre-Requisites
- Install Python 3.12

## How to run
1. Clone this repository and the packet interceptor repository
2. Make a strategy in the controller and pass it as parameter to the serve method in main
3. Configure the ports and amount of validator nodes to use in the interceptor in the `network-config.toml` file
4. Run the controller
5. Run the interceptor

Below is a guide on how to run the controller module. Refer to the interceptor repository for instructions on how to run the interceptor module.

### Linux
```console
user@laptop:~$ git clone git@gitlab.ewi.tudelft.nl:cse2000-software-project/2023-2024/cluster-q/13d/xrpl-controller-module.git
user@laptop:~$ cd xrpl-controller-module
user@laptop:~$ python -m venv .venv               # Recommended: create a virtual environment
user@laptop:~$ source .venv/bin/activate          # Activate the virtual env
user@laptop:~$ pip install -r requirements.txt    # Install requirements
user@laptop:~$ python3 -m xrpl_controller         # Runs the application
```


### Windows
```console
PS > git clone git@gitlab.ewi.tudelft.nl:cse2000-software-project/2023-2024/cluster-q/13d/xrpl-controller-module.git
PS > cd xrpl-controller-module
PS > python -m venv .venv               # Recommended: create a virtual environment
PS > ./.venv/Scripts/activate           # Activate the virtual env
PS > pip install -r requirements.txt    # Install requirements
PS > python3 -m xrpl_controller         # Runs the application
```

It is recommended to create a Virtual Environment using the command (executed in the root of the repository): `python -m venv .venv` This command will create a virtual environment in a subfolder `.venv`, pyCharm should automatically pick this up and use it by default.

## How to contribute
1. Create a new branch from `main`
2. Make your changes
3. Make sure the pipeline passes
4. Push your branch to the repository
5. Create a merge request to `main`

### The pipeline
Current included stages:
- Unit testing using [pytest](https://docs.pytest.org/en/8.2.x/)
- Linting using [ruff](https://docs.astral.sh/ruff/)
- Type checking using [mypy](https://mypy.readthedocs.io/en/stable/)
- Style checking/formatting using [ruff](https://docs.astral.sh/ruff/)
- Automatic documentation generation using [Sphinx](https://www.sphinx-doc.org) and [Read-the-Docs](https://docs.readthedocs.io/en/stable/)

### Unit Testing & Static Analysis
To run the different pipeline stages, excluding the automatic documentation generation, [tox](https://tox.wiki/en/4.15.0/user_guide.html) is used.
`tox` makes sure every stage of the pipeline runs in a separate environment, which eliminates interference. Another benefit of `tox` is the ability to execute the `tox` command in a local terminal, which will run unit testing, type checking, linting and style checking locally, meaning you do not have to push your changes to GitLab to check whether the pipeline will fail or pass.

#### Linux
```console
user@laptop:~$ tox                                # Runs pipeline locally (without documentation generation)
```

#### Windows
```console
PS > tox                                # Runs pipeline locally (without documentation generation)
```

### Documentation Generation
The automated documentation generation will only run on a merge to main. After successful execution, it will publish the generated HTML on [GitLab Pages](https://docs.gitlab.com/ee/user/project/pages/) automatically, which means the most recent version of the documentation will always be available through our repository.

Below you can find how to generate documentation locally

#### Linux
```console
user@laptop:~$ cd docs
user@laptop:~$ make clean && make html
```

#### Windows
```console
PS > cd docs
PS > ./make.bat clean
PS > ./make.bat html
```

The documentation website files should now be in `docs/_build/html`. Then, inside this folder, you can open `index.html` with your browser.

### gRPC
If you want to make changes to a .proto file it is important that you make the exact same changes in the corresponding file in the interceptor and regenerate the necessary files both in the controller and interceptor. 
- For the controller run:
```
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. protos/packet.proto
```
- For the interceptor you can just rebuild.


### Logging
Users are able to log custom columns to a csv file using the class `CSVLogger` in `csv_logger.py`, which will automatically open up a csv file using a filename, specified columns, and optional subdirectory.

#### Action Logs
Action logs can be kept track of by using the `keep_log` boolean argument in the `serve` method in `packet_server.py`. When this argument is set to `True`, 
an action log (csv) will be kept under the `logs/action_logs/[start_time]` directory along with a csv file containing the information of the validator nodes which were used during logging process. 
This action log makes use of the `CSVLogger`'s child class `ActionLogger` which is dedicated to logging actions. 
The log contains the timestamp when the action was taken on a packet, the action, sender peer port, receiver peer port, and the packet data as a hex string.


### Adding new strategies
To add a new strategy, you need to create a new file in the `strategies` folder with a class that inherits from the `Strategy` class. This class should implement the `handle_packet` method.

#### Network Partitions
Newly created `Strategy`'s should call `super().__init__()` to initialize needed fields to support network partitions.
Use `self.partition_network(partition: list[list[int]])` to partition the network using the validators' peer ports as id's in the partitions.
Example usage with a network of 3 nodes with peer ports `0`, `1`, and `2` respectively where `0` will be isolated and `1` and `2` will be in the same partition: `self.partition_network([[0], [1, 2]])`.
The user has the choice to set automatic network partition application using the boolean field `self.auto_partition`, this defaults to `True`.
The user can apply partitions manually by using 
`self.apply_network_partition(action: int, peer_from_port: int, peer_to_port: int)` which will transform an arbitrary action to a `drop` action when `peer_from_port` is not in the same partition as `peer_to_port`.
Any other network partition-related field should not be modified by the user themselves. Custom partitions can be realized by modifying the boolean matrix `self.communication_matrix`, although it is not recommended to do so manually.

### System-level Automated Testing
We have included some system-level automated tests. These can be run using `python -m tests.system_level`. Make sure Docker is running before you start the tests, to ensure correct execution.
