import yaml
from datetime import datetime
import argparse
from pathlib import Path
from utils import get_dirs, get_date_time_strf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="evotest_parallel.py",
        description="run different modes of random and evo testing for ripple.",
    )

    parser.add_argument(
        "--ripple-image",
        type=str,
        default="xrpllabsofficial/xrpld:2.6.0",
        metavar="RIPPLE_IMAGE",
        help="the docker image to use for the rippled instances (default: xrpllabsofficial/xrpld:2.6.0)",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=98,
        metavar="SEED",
        help="the random seed",
    )

    parser.add_argument(
        "--min-delay-ms",
        type=int,
        default=0,
        metavar="MIN_DELAY_MS",
        help="the minimum delay in milliseconds (default: 0)",
    )

    parser.add_argument(
        "--max-delay-ms",
        type=int,
        default=100,
        metavar="MAX_DELAY_MS",
        help="the maximum delay in milliseconds (default: 100)",
    )

    parser.add_argument(
        "--rust-log-level",
        type=str,
        default="info",
        choices=["trace", "debug", "info", "warn", "error"],
        metavar="RUST_LOG_LEVEL",
        help="the log level for Rust code (default: info)",
    )

    parser.add_argument(
        "--byzz-min-seq",
        type=int,
        default=5,
        metavar="BYZZ_MIN_SEQ",
        help="starting seq to perform byzz behavior (default: 5)",
    )

    parser.add_argument(
        "--byzz-max-seq",
        type=int,
        default=10,
        metavar="BYZZ_MAX_SEQ",
        help="ending seq to perform byzz behavior (default: 10)",
    )

    parser.add_argument(
        "--max-ledger-seq",
        type=int,
        default=15,
        metavar="MAX_LEDGER_SEQ",
        help="the maximum ledger sequence number to run the tests (default: 15)",
    )

    parser.add_argument(
        "--total-num-tests",
        type=int,
        default=500,
        metavar="TOTAL_NUM_TESTS",
        help="the total number of tests to run (default: 500)",
    )

    parser.add_argument(
        "--population-size",
        type=int,
        default=10,
        metavar="POPULATION_SIZE",
        help="the population size only used for the evolutionary algorithm (default: 10)",
    )

    parser.add_argument(
        "--fitness-function",
        type=str,
        default="mean_validation_time",
        choices=[
            "num_propose_set",
            "num_getledger_hashes",
            "num_getledger_messages",
            "mean_validation_time",
            "var_validation_time",
            "validation_distribution_entropy",
            "message_entropy_integral",
            "message_entropy_average",
            "markov_matrix_non_similarity",
            "gossip_fiedler",
        ],
        metavar="FITNESS_FUNCTION",
        help="the fitness function to use only for the evolutionary algorithm (default: mean_validation_time)",
    )

    parser.add_argument(
        "--strategy",
        type=str,
        # TODO: 自动获取rocket_controller.strategies模块下的所有strategy的子类
        choices=[
            "EvoDelayStrategy",
            "EvoDelayByzzPartitionStrategy",
            "RandomDelayByzzStrategy",
            "RandomByzzStrategy",
            "RandomDelayStrategy",
            "EvoDelayBySeqStrategy",
            "RandomDelayByzzPartitionStrategy",
            "ComposedStrategy",
        ],
        default="EvoDelayStrategy",
        metavar="STRATEGY",
        help="the name of the rocket_controller strategy class to use (e.g. EvoDelayStrategy)",
    )

    parser.add_argument(
        "--max-parallel-workers",
        type=int,
        default=1,
        metavar="MAX_PARALLEL_WORKERS",
        help="the maximum number of parallel workers to use for running tests (default: 1)",
    )

    parser.add_argument(
        "--base-network-config-yaml",
        type=str,
        default="network.yaml",
        metavar="NETWORK_BASE_CONFIG_YAML",
        help="the YAML file for (base) network configuration (default: network.yaml)",
    )

    parser.add_argument(
        "--mu",
        type=int,
        default=4,
        metavar="MU",
        help="the number of offspring to produce in each generation for the evolutionary algorithm (default: 4)",
    )

    parser.add_argument(
        "--timeout-per-seq",
        type=int,
        default=30,
        metavar="TIMEOUT_PER_SEQ",
        help="the timeout in seconds for each ledger sequence (default: 30)",
    )

    parser.add_argument(
        "--individual-timeout-sec",
        type=int,
        default=None,
        metavar="IND_TIMEOUT",
        help=(
            "maximum seconds allowed for one individual evaluation; "
            "if omitted, defaults to max_ledger_seq * timeout_per_seq * 2"
        ),
    )

    # logging options
    parser.add_argument(
        "--logs-group-dir",
        type=str,
        default=None,
        metavar="LOGS_GROUP_DIR",
        help="(optional) root directory under which all test logs will be placed; if not supplied a timestamped folder is generated",
    )

    # port allocation for entire population (see run_evotests.py for an example
    # of how this can be used to reserve a chunk of ports per configuration
    # combination).
    parser.add_argument(
        "--base-port-population",
        type=int,
        default=60000,
        metavar="BASE_PORT_POPULATION",
        help=(
            "starting port number that will be handed to the first individual; "
            "subsequent individuals will be assigned higher ports to avoid collisions"
        ),
    )

    parser.add_argument(
        "--output-screen",
        action="store_true", # 这里表示这是个flag，如果出现则为true
        help="if set, controller stdout/stderr are printed to the screen instead of being redirected",
    )

    parser.add_argument(
        "--grpc-base-port",
        type=int,
        default=50051,
        metavar="GRPC_BASE_PORT",
        help="the starting gRPC port; each instance will add its own offset",
    )

    parser.add_argument(
        "--partition-seq",
        type=int,
        default=5,
        metavar="PARTITION_SEQ",
        help="the starting ledger sequence for network partition (default: 5)",
    )

    parser.add_argument(
        "--partition-duration",
        type=int,
        default=1000,
        metavar="PARTITION_DURATION",
        help="the duration of the network partition in milliseconds (default: 1000)",
    )

    parser.add_argument(
        "--delay-mode",
        type=str,
        default=None,
        choices=["none", "random", "dense_rules", "dense_seq_rules", "sparse_rules"],
    )

    parser.add_argument(
        "--partition-mode",
        type=str,
        default=None,
        choices=["none", "random_bipart", "bi_part_groups"],
    )

    parser.add_argument(
        "--byzz-mode",
        type=str,
        default=None,
        choices=["none", "random", "sparse_rules"],
    )

    parser.add_argument(
        "--force-exit-on-second-sigint",
        action="store_true",
        help="if set, pressing Ctrl+C twice will force evotest_parallel to exit immediately",
    )

    return parser.parse_args()


def extend_configs(args: argparse.Namespace) -> dict:
    configs = vars(args)
    dirs = get_dirs(__file__)
    configs = {**configs, **dirs}

    with open(configs["cur_dir"] / configs["base_network_config_yaml"], "r") as f:
        network_config = yaml.safe_load(f)
        # apply CLI overrides for base ports if provided
        for key in [
            ("base_port_peer", "base_port_peer"),
            ("base_port_ws", "base_port_ws"),
            ("base_port_ws_admin", "base_port_ws_admin"),
            ("base_port_rpc", "base_port_rpc"),
        ]:
            cli_name, cfg_name = key
            if configs.get(cli_name) is not None:
                network_config[cfg_name] = configs[cli_name]

        configs["base_network_config"] = network_config
        configs["number_of_nodes"] = network_config.get("number_of_nodes")
        configs["byzz_nodes"] = network_config.get("byzz_nodes")

    # 推导max_generation
    configs["max_generation"] = configs["total_num_tests"] // configs["population_size"]

    # derive individual timeout when the user did not provide one explicitly
    if configs.get("individual_timeout_sec") is None:
        max_ledger_seq = int(configs.get("max_ledger_seq", 15) or 15)
        timeout_per_seq = int(configs.get("timeout_per_seq", 30) or 30)
        configs["individual_timeout_sec"] = max_ledger_seq * timeout_per_seq * 2

    # expose the path to the base network yaml for helpers that need it
    configs["network_yaml"] = configs["cur_dir"] / configs["base_network_config_yaml"]

    # output behaviour for individual runs (mostly for debugging small
    # populations).  default is False unless caller explicitly asked for it.
    configs["output_screen"] = configs.get("output_screen", False)

    # determine where logs will go. if the caller supplied an explicit
    # directory, we respect it verbatim; it is assumed to already include
    # whatever grouping (strategy/fitness/image/etc.) the caller desires.
    # when no directory is provided we create logs under:
    #   logs/<datetime>/<folder>
    # where <folder> defaults to the strategy name.
    if configs.get("logs_group_dir"):
        # user gave a path to use for this specific test run – do not
        # modify it further.
        configs["test_log_dir"] = Path(configs["logs_group_dir"])
    else:
        configs["test_log_dir"] = Path(configs["logs_dir"]) / get_date_time_strf()

    return configs


def get_configs() -> dict:
    args = parse_args()
    return extend_configs(args)


if __name__ == "__main__":
    configs = get_configs()
    for key, value in configs.items():
        print(f"{key}: {value}. ({type(value)})")
