//! This module is responsible for setting up and tearing down the Docker containers who run the validator nodes.

use log::{debug, info};
use std::env::current_dir;
use std::fs;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;
use std::time::Duration;

use bollard::container::{CreateContainerOptions, RemoveContainerOptions};
use bollard::exec::{CreateExecOptions, StartExecResults};
use bollard::image::CreateImageOptions;
use bollard::models::{HostConfig, Mount, MountTypeEnum, PortBinding, PortMap};
use bollard::Docker;

use crate::is_valid_unl_connection;
use crate::packet_client::proto;
use crate::packet_client::PacketClient;
use futures_util::stream::StreamExt;
use futures_util::TryStreamExt;
use serde::Deserialize;
use serde_json::Value;

const DEFAULT_IMAGE: &str = "xrpllabsofficial/xrpld:2.3.0";

/// Struct that represents a response of a 'ValidationKeyCreate' request.
#[derive(Debug, Deserialize)]
struct ValidationKeyCreateResponse {
    /// The result of the request.
    result: ValidatorKeyData,
}

/// Struct that represents all the data used for validation by nodes.
#[derive(Debug, Deserialize, Clone, PartialEq)]
pub struct ValidatorKeyData {
    /// The status of the request that was used to make this data.
    pub status: String,
    /// The validation key of a node.
    pub validation_key: String,
    /// The validation private key of a node.
    pub validation_private_key: String,
    /// The validation public key of a node.
    pub validation_public_key: String,
    /// The seed used to make this validation info.
    pub validation_seed: String,
}

/// Struct that represents a Docker container that runs a rippled instance.
#[derive(Debug, Clone)]
pub struct DockerContainer {
    /// The id of the container.
    pub id: Option<String>,
    /// The name of the container.
    pub name: String,
    /// The port where the node listens for peer connections.
    pub port_peer: u32,
    /// The port where the node listens for WebSocket connections.
    pub port_ws: u32,
    /// The port where the node listens for WebSocket connections for admins.
    pub port_ws_admin: u32,
    /// The port where the node listens for RPC requests.
    pub port_rpc: u32,
    /// The data of the keys of this node.
    pub key_data: ValidatorKeyData,
}

/// Checks whether a certain `DockerContainer` is available by calling `server_info` and parsing the `success` value.
///
/// # Parameters
/// * 'container' - the container to be checked.
/// * 'docker' - the Docker interface used for API requests.
///
/// # Panics
/// * If the 'id' of the container could not be cloned.
/// * If the creation of the 'server_info' command raised an error.
/// * If the 'server_info' command ran inside the docker container raised an error.
/// * If the output could not be parsed to JSON.
/// * If the JSON could not be parsed to a serde_json object.
async fn check_validator_available(container: DockerContainer, docker: Docker) -> bool {
    let exec = docker
        .clone()
        .create_exec(
            container.id.clone().unwrap().as_ref(),
            CreateExecOptions {
                attach_stdout: Some(true),
                cmd: Some(vec!["rippled", "server_info"]),
                ..Default::default()
            },
        )
        .await
        .unwrap()
        .id;
    if let StartExecResults::Attached { mut output, .. } =
        docker.clone().start_exec(&exec, None).await.unwrap()
    {
        while let Some(Ok(msg)) = output.next().await {
            let json_str = String::from_utf8(msg.as_ref().to_vec()).unwrap();
            let server_info_data: Value = serde_json::from_str(json_str.as_str()).unwrap();
            if server_info_data["result"]["status"] == "success" {
                debug!("{} Available!", container.name.clone());
                return true;
            }
            debug!("{} not available yet...", container.name.clone());
        }
    }
    false
}

/// Struct that represents the whole network of Docker containers.
#[derive(Debug)]
pub struct DockerNetwork {
    /// The network configuration as a proto object.
    pub config: proto::Config,
    /// A Vec of all the individual Docker containers who run a rippled instance.
    pub containers: Vec<DockerContainer>,
    /// A Docker object to access the Docker API.
    docker: Docker,
    /// Instance ID for parallel execution.
    instance_id: String,
}

impl DockerNetwork {
    /// Initializes a new DockerNetwork.
    ///
    /// # Parameters
    /// * 'config' - the config to be used to set up the network.
    pub fn new(config: proto::Config) -> DockerNetwork {
        // instance id: if not in env, set to empty string
        let instance_id = std::env::var("ROCKET_CLUSTER_ID")
            .unwrap_or_else(|_| "".to_string());
        DockerNetwork {
            config,
            containers: Vec::new(),
            docker: Docker::connect_with_local_defaults().unwrap(),
            instance_id,
        }
    }

    /// Root directory inside the repository that stores static interceptor
    /// assets such as the base rippled config and ledger file.
    fn get_static_network_root(&self) -> PathBuf {
        current_dir()
            .expect("Could not determine current directory")
            .join("network")
    }

    /// Root directory on the host where generated validator/key-generator
    /// configs are stored for a run.
    fn get_generated_network_root(&self) -> PathBuf {
        if let Ok(root) = std::env::var("ROCKET_NETWORK_ROOT") {
            return PathBuf::from(root);
        }

        if let Ok(tmp_root) = std::env::var("ROCKET_TMPDIR") {
            return PathBuf::from(tmp_root).join("network");
        }

        if let Ok(tmp_root) = std::env::var("TMPDIR") {
            return PathBuf::from(tmp_root).join("network");
        }

        PathBuf::from("/tmp/rocket-tmp/network")
    }

    /// Root directory on the host where validator runtime data is stored.
    ///
    /// We prefer an explicit env var so outer runner containers can point to a
    /// path that exists identically on host and inside the runner container.
    /// When missing, default under the temporary directory so validator runtime
    /// data does not accumulate in Docker's global storage root.
    fn get_volumes_root(&self) -> PathBuf {
        if let Ok(root) = std::env::var("ROCKET_VOLUMES_ROOT") {
            return PathBuf::from(root);
        }

        if let Ok(tmp_root) = std::env::var("ROCKET_TMPDIR") {
            return PathBuf::from(tmp_root).join("volumes");
        }

        if let Ok(tmp_root) = std::env::var("TMPDIR") {
            return PathBuf::from(tmp_root).join("volumes");
        }

        PathBuf::from("/tmp/rocket-tmp/volumes")
    }

    /// Create the runtime directories for one container under the shared
    /// volumes root and return the host paths for its DB and log directories.
    fn ensure_runtime_dirs(&self, container_name: &str) -> (PathBuf, PathBuf) {
        let container_root = self.get_volumes_root().join(container_name);
        let db_dir = container_root.join("db");
        let log_dir = container_root.join("log");

        fs::create_dir_all(&db_dir).expect("Could not create validator db directory");
        fs::create_dir_all(&log_dir).expect("Could not create validator log directory");

        (db_dir, log_dir)
    }

    fn ensure_key_generator_config_dir(&self, container_name: &str) -> PathBuf {
        let config_dir = self
            .get_generated_network_root()
            .join(container_name)
            .join("config");
        fs::create_dir_all(&config_dir).expect("Could not create key_generator config directory");
        config_dir
    }

    fn ensure_validator_config_dir(&self, container_name: &str) -> PathBuf {
        let config_dir = self
            .get_generated_network_root()
            .join("validators")
            .join(container_name)
            .join("config");
        fs::create_dir_all(&config_dir).expect("Could not create validator config directory");
        config_dir
    }

    /// Run inner containers as the same uid:gid as the outer runner user when
    /// available, so bind-mounted files stay user-writable on the host.
    fn get_container_user(&self) -> Option<String> {
        let uid = std::env::var("ROCKET_HOST_UID").ok()?;
        let gid = std::env::var("ROCKET_HOST_GID").ok()?;
        Some(format!("{uid}:{gid}"))
    }

    /// Initializes the docker network by generating keys for each configured node, and starting
    /// them using `bollard`. The containers that were started successfully are appended to
    /// the `containers` field in the struct.
    ///
    /// # Parameters
    /// * 'client' - a PacketClient to send the ValidatorNodeInfo to the controller.
    ///
    /// # Panics
    /// * If an error occurred while sending the ValidatorNodeInfo to the controller.
    pub async fn initialize_network(&mut self, mut client: PacketClient) {
        // Stop all running validator nodes before starting new network
        self.stop_network().await;
        self.download_image().await;

        let validator_keys = self.generate_keys(self.config.number_of_nodes as u16).await;
        let names_with_keys = self.generate_validator_configs(&validator_keys);

        let base_port_peer = self.config.base_port_peer;
        let base_port_ws = self.config.base_port_ws;
        let base_port_ws_admin = self.config.base_port_ws_admin;
        let base_port_rpc = self.config.base_port_rpc;

        let mut validator_node_info_list = vec![];

        for (i, (name, keys)) in names_with_keys.iter().enumerate() {
            let mut validator_container = DockerContainer {
                id: None,
                name: name.clone(),
                port_peer: base_port_peer + i as u32,
                port_ws: base_port_ws + i as u32,
                port_ws_admin: base_port_ws_admin + i as u32,
                port_rpc: base_port_rpc + i as u32,
                key_data: keys.clone(),
            };
            self.start_validator(&mut validator_container).await;
            info!("Started docker container {}", name.clone());
            validator_node_info_list.push(proto::ValidatorNodeInfo {
                peer_port: validator_container.port_peer,
                ws_public_port: validator_container.port_ws,
                ws_admin_port: validator_container.port_ws_admin,
                rpc_port: validator_container.port_rpc,
                status: validator_container.key_data.status.clone(),
                validation_key: validator_container.key_data.validation_key.clone(),
                validation_private_key: validator_container.key_data.validation_private_key.clone(),
                validation_public_key: validator_container.key_data.validation_public_key.clone(),
                validation_seed: validator_container.key_data.validation_seed.clone(),
            });
            self.containers.push(validator_container);
        }
        client
            .send_validator_node_info(validator_node_info_list)
            .await
            .unwrap();
    }

    /// Stops the docker network, by looping over all running containers (`docker ps`)
    /// and stopping all containers that start with `validator_` or `key_generator`.
    ///
    /// # Panics
    /// * If it could not fetch the list of running containers from the Docker API.
    /// * If it could not terminate any running container.
    pub async fn stop_network(&self) {
        let running_containers = self
            .docker
            .list_containers::<String>(None)
            .await
            .expect("Could not fetch container list from docker");
        for container in running_containers {
            if let Some(names) = container.names {
                for name in names {
                    debug!("{}", name);
                    // Docker container names always start with a slash
                    let instance_id = &self.instance_id;
                    let should_stop = if instance_id.is_empty() {
                        name.starts_with("/validator_") || name.eq("/key_generator")
                    } else {
                        name.starts_with(format!("/{instance_id}_validator_").as_str())
                            || name.eq(format!("/{instance_id}_key_generator").as_str())
                    };
                    if should_stop {
                        debug!(
                            "Stopping container (auto removed): {}",
                            container.id.clone().unwrap().as_str()
                        );
                        self.docker
                            .stop_container(container.id.clone().unwrap().as_str(), None)
                            .await
                            .unwrap();

                        // Poll until the container is no longer in the list of running containers
                        loop {
                            let containers =
                                self.docker.list_containers::<String>(None).await.unwrap();
                            if containers.iter().all(|c| c.id != container.id) {
                                break;
                            }
                            tokio::time::sleep(Duration::from_millis(200)).await;
                        }
                    }
                }
            }
        }
    }

    /// Loop over all containers in `self`, and poll them every 500ms, until
    /// all containers are available.
    pub async fn wait_for_startup(&self) {
        let mut threads = vec![];
        let arc = self.docker.clone();
        for container in self.containers.clone() {
            let _docker = arc.clone();
            let t = tokio::spawn(async move {
                loop {
                    if check_validator_available(container.clone(), _docker.clone()).await {
                        break;
                    }
                    tokio::time::sleep(Duration::from_millis(500)).await;
                }
            });
            threads.push(t);
        }

        for t in threads {
            t.await.expect("Wait for startup failed for thread");
        }
    }

    /// Downloads the 'isvanloon/rippled-no-sig-check:latest' image from DockerHub.
    ///
    /// # Panics
    /// * If an error occurred while downloading the image.
    async fn download_image(&mut self) {
        let image = self.get_image_from_env();
        info!("Checking for docker image '{}'", image);
        // Check whether the image already exists locally. If so, skip pulling.
        match self.docker.list_images::<String>(None).await {
            Ok(images) => {
                for img in images.iter() {
                    // `repo_tags` is a Vec<String> here; check tags directly
                    if img.repo_tags.iter().any(|t| t == &image) {
                        info!("Docker image '{}' found locally, skipping pull", image);
                        return;
                    }
                }
            }
            Err(e) => {
                debug!("Failed to list images: {}", e);
            }
        }

        info!("Pulling docker image '{}'", image);
        self.docker
            .create_image(
                Some(CreateImageOptions {
                    from_image: image.as_str(),
                    ..Default::default()
                }),
                None,
                None,
            )
            .try_collect::<Vec<_>>()
            .await
            .unwrap();
    }

    /// Starts a validator node.
    /// It binds specific ports of the container to be able to communicate with the nodes.
    /// Besides, it starts the validator node with a specified ledger to have all amendments already included.
    ///
    /// # Parameters
    /// * 'container' - the container to be started.
    ///
    /// # Panics
    /// * If it could not format the directory path to the 'config' directory.
    /// * If the Docker container who runs the validator could not be created or started.
    async fn start_validator(&self, container: &mut DockerContainer) {
        let image = self.get_image_from_env();
        let (db_dir, log_dir) = self.ensure_runtime_dirs(container.name.as_str());
        let config_dir = self.ensure_validator_config_dir(container.name.as_str());
        let container_user = self.get_container_user();
        let mut port_map = PortMap::new();
        port_map.insert(
            String::from("51235/tcp"),
            Some(vec![PortBinding {
                host_port: Some(container.port_peer.to_string()),
                ..Default::default()
            }]),
        );
        port_map.insert(
            String::from("6006/tcp"),
            Some(vec![PortBinding {
                host_port: Some(container.port_ws_admin.to_string()),
                ..Default::default()
            }]),
        );
        port_map.insert(
            String::from("5005/tcp"),
            Some(vec![PortBinding {
                host_port: Some(container.port_rpc.to_string()),
                ..Default::default()
            }]),
        );

        let create_options = CreateContainerOptions {
            name: container.name.as_str(),
            ..Default::default()
        };

        let container_config = bollard::container::Config {
            image: Some(image.as_str()),
            user: container_user.as_deref(),
            env: Some(vec!["ENV_ARGS=--start --ledgerfile /config/ledger.json"]),
            host_config: Some(HostConfig {
                auto_remove: Some(true),
                port_bindings: Some(port_map),
                mounts: Some(vec![
                    Mount {
                        target: Some(String::from("/config")),
                        source: Some(config_dir.to_string_lossy().to_string()),
                        typ: Some(MountTypeEnum::BIND),
                        ..Default::default()
                    },
                    Mount {
                        target: Some(String::from("/var/lib/rippled/db")),
                        source: Some(db_dir.to_string_lossy().to_string()),
                        typ: Some(MountTypeEnum::BIND),
                        ..Default::default()
                    },
                    Mount {
                        target: Some(String::from("/var/log/rippled")),
                        source: Some(log_dir.to_string_lossy().to_string()),
                        typ: Some(MountTypeEnum::BIND),
                        ..Default::default()
                    },
                ]),
                ..Default::default()
            }),
            ..Default::default()
        };

        match self
            .docker
            .create_container::<&str, &str>(Some(create_options), container_config)
            .await
        {
            Ok(container_response) => {
                let id = container_response.id;
                match self.docker.start_container::<String>(&id, None).await {
                    Ok(_) => {
                        container.id = Some(id.clone());
                    }
                    Err(e) => {
                        panic!("Failed to start the xrpld container, try checking your base port configuration values to make sure they are not bound by another process: {}", e);
                    }
                }
            }
            Err(e) => {
                panic!("Failed to create container: {}", e);
            }
        }
    }

    /// Generates `n` validator keys using a `rippled` instance.
    ///
    /// # Parameters
    /// * 'n' - the amount of validator keys to generate.
    ///
    /// # Panics
    /// * If the JSON response from `rippled` cannot be correctly deserialized to the `ValidationKeyCreateResponse` struct.
    /// * If an error occurred while creating or starting the Docker container who generates the keys.
    /// * If an error occurred while creating or executing the 'validation_create' command.
    /// * If an error occurred while removing the Docker container who generated the keys.
    async fn generate_keys(&self, n: u16) -> Vec<ValidatorKeyData> {
        let container_name = if self.instance_id.is_empty() {
            String::from("key_generator")
        } else {
            format!("{}_key_generator", self.instance_id)
        };
        let (db_dir, log_dir) = self.ensure_runtime_dirs(container_name.as_str());
        let config_dir = self.ensure_key_generator_config_dir(container_name.as_str());
        let container_user = self.get_container_user();


        let create_options = CreateContainerOptions {
            name: container_name.as_str(),
            ..Default::default()
        };

        let image = self.get_image_from_env();
        let container_config = bollard::container::Config {
            image: Some(image.as_str()),
            user: container_user.as_deref(),
            host_config: Some(HostConfig {
                auto_remove: Some(true),
                mounts: Some(vec![
                    Mount {
                        target: Some(String::from("/config")),
                        source: Some(config_dir.to_string_lossy().to_string()),
                        typ: Some(MountTypeEnum::BIND),
                        ..Default::default()
                    },
                    Mount {
                        target: Some(String::from("/var/lib/rippled/db")),
                        source: Some(db_dir.to_string_lossy().to_string()),
                        typ: Some(MountTypeEnum::BIND),
                        ..Default::default()
                    },
                    Mount {
                        target: Some(String::from("/var/log/rippled")),
                        source: Some(log_dir.to_string_lossy().to_string()),
                        typ: Some(MountTypeEnum::BIND),
                        ..Default::default()
                    },
                ]),
                ..Default::default()
            }),
            ..Default::default()
        };

        let id = self
            .docker
            .create_container::<&str, &str>(Some(create_options), container_config)
            .await
            .unwrap()
            .id;

        self.docker
            .start_container::<String>(&id, None)
            .await
            .unwrap();

        loop {
            if check_validator_available(
                DockerContainer {
                    id: Some(id.clone()),
                    name: container_name.clone(),
                    port_peer: 0,
                    port_ws: 0,
                    port_ws_admin: 0,
                    port_rpc: 0,
                    key_data: ValidatorKeyData {
                        status: "success".to_string(),
                        validation_key: "".to_string(),
                        validation_private_key: "".to_string(),
                        validation_public_key: "".to_string(),
                        validation_seed: "".to_string(),
                    },
                },
                self.docker.clone(),
            )
            .await
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }

        // Generate the keys and parse the output
        let mut key_vec: Vec<ValidatorKeyData> = Vec::new();
        for _ in 0..n {
            let exec = self
                .docker
                .create_exec(
                    &id,
                    CreateExecOptions {
                        attach_stdout: Some(true),
                        cmd: Some(vec!["rippled", "validation_create"]),
                        ..Default::default()
                    },
                )
                .await
                .unwrap()
                .id;
            if let StartExecResults::Attached { mut output, .. } =
                self.docker.start_exec(&exec, None).await.unwrap()
            {
                while let Some(Ok(msg)) = output.next().await {
                    let json_str = String::from_utf8(msg.as_ref().to_vec()).unwrap();
                    let validator_key_data: ValidationKeyCreateResponse =
                        serde_json::from_str(json_str.as_str()).unwrap();

                    key_vec.push(validator_key_data.result);
                }
            }
        }

        self.docker
            .remove_container(
                &id,
                Some(RemoveContainerOptions {
                    force: true,
                    ..Default::default()
                }),
            )
            .await
            .unwrap();
        key_vec
    }

    /// Generates and writes the config files for every key in `keys` to disk. The configurations
    /// are saved to /network/validators/\<name\>.
    ///
    /// # Panics
    /// * If the `rippled_base.cfg` cannot be read.
    /// * If the config could not be written to disk (no permissions/directory does not exist).
    fn generate_validator_configs(
        &self,
        keys: &[ValidatorKeyData],
    ) -> Vec<(String, ValidatorKeyData)> {
        let static_network_root = self.get_static_network_root();
        let base_config_path = static_network_root.join("rippled_base.cfg");
        let ledger_json_path = static_network_root.join("ledger.json");
        let base_config_file = fs::File::open(&base_config_path);

        let mut base_config_contents = String::new();
        base_config_file
            .unwrap()
            .read_to_string(&mut base_config_contents)
            .unwrap_or_else(|_| panic!("Could not read file {}", base_config_path.display()));

        let mut ret: Vec<(String, ValidatorKeyData)> = Vec::new();
        for (i, key) in keys.iter().enumerate() {
            let container_name = if self.instance_id.is_empty() {
                format!("validator_{}", i)
            } else {
                format!("{}_validator_{}", self.instance_id, i)
            };
            let new_config_contents = base_config_contents
                .clone()
                .replace("{validation_seed}", key.validation_seed.as_str());

            let config_dir = self.ensure_validator_config_dir(container_name.as_str());

            let mut config_file = fs::File::create(config_dir.join("rippled.cfg")).unwrap();
            config_file
                .write_all(new_config_contents.as_bytes())
                .expect("Could not write to config file");

            let mut validators_file = fs::File::create(config_dir.join("validators.txt")).unwrap();

            let unl_public_keys: Vec<String> = keys
                .iter()
                .enumerate()
                .filter(|(j, _)| {
                    is_valid_unl_connection(i as u32, *j as u32, &self.config.unl_partitions)
                })
                .map(|(_, k)| k.validation_public_key.to_string())
                .collect();

            validators_file
                .write_all(format!("[validators]\n{}", unl_public_keys.join("\n")).as_bytes())
                .expect("Could not write to config file");

            fs::copy(ledger_json_path.as_path(), config_dir.join("ledger.json")).unwrap();

            ret.push((container_name, key.clone()));
        }
        ret
    }

    /// Read ripple image name from the environment variable `RIPPLE_IMAGE`.
    /// Falls back to DEFAULT_IMAGE when missing or on error.
    fn get_image_from_env(&self) -> String {
        if let Ok(image) = std::env::var("RIPPLE_IMAGE") {
            return image;
        }
        DEFAULT_IMAGE.to_string()
    }
}

#[cfg(test)]
mod integration_tests_docker {
    use super::*;
    use crate::packet_client;
    use crate::packet_client::proto::Config;

    fn docker_network_setup() -> DockerNetwork {
        let config = Config {
            base_port_peer: 60000,
            base_port_ws: 61000,
            base_port_ws_admin: 62000,
            base_port_rpc: 63000,
            number_of_nodes: 3,
            net_partitions: vec![],
            unl_partitions: vec![],
        };
        DockerNetwork::new(config)
    }

    // Note: This test requires running a docker engine in clean state
    // Tests the generate_keys function; assert that the keys are generated and the container is removed
    #[tokio::test]
    // #[coverage(off)]  // Only available in nightly build, don't forget to uncomment #![feature(coverage_attribute)] on line 1 of main
    async fn test_generate_keys() {
        let docker_network = docker_network_setup();
        assert_eq!(
            docker_network
                .docker
                .list_containers::<String>(None)
                .await
                .unwrap()
                .len(),
            0,
            "This test requires a clean docker starting state"
        );
        let keys = docker_network.generate_keys(3).await;
        assert_eq!(keys.len(), 3);
        assert_eq!(
            docker_network
                .docker
                .list_containers::<String>(None)
                .await
                .unwrap()
                .len(),
            0,
            "Docker containers were not removed correctly"
        );
    }

    // Tests the generate_validator_configs function; assert that the config files are correctly created
    #[test]
    // #[coverage(off)]  // Only available in nightly build, don't forget to uncomment #![feature(coverage_attribute)] on line 1 of main
    fn test_generate_validator_configs() {
        let keys = vec![
            ValidatorKeyData {
                status: "success".to_string(),
                validation_key: "val_key1".to_string(),
                validation_private_key: "priv_key1".to_string(),
                validation_public_key: "pub_key1".to_string(),
                validation_seed: "seed1".to_string(),
            },
            ValidatorKeyData {
                status: "success".to_string(),
                validation_key: "val_key2".to_string(),
                validation_private_key: "priv_key2".to_string(),
                validation_public_key: "pub_key2".to_string(),
                validation_seed: "seed2".to_string(),
            },
        ];
        let docker_network = docker_network_setup();
        let configs = docker_network.generate_validator_configs(&keys);
        assert_eq!(configs.len(), 2);
        assert_eq!(configs[0].0, "validator_0");
        assert_eq!(configs[1].0, "validator_1");
        assert_eq!(configs[0].1, keys[0]);
        assert_eq!(configs[1].1, keys[1]);

        // check if the files for the first validator are created
        let dir1 = docker_network
            .get_generated_network_root()
            .join("validators")
            .join("validator_0")
            .join("config");
        assert!(
            fs::metadata(dir1.join("ledger.json")).is_ok(),
            "File not found, path: {:?}",
            dir1.join("ledger.json")
        );
        assert!(
            fs::metadata(dir1.join("rippled.cfg")).is_ok(),
            "File not found, path: {:?}",
            dir1.join("rippled.cfg")
        );
        let validators_txt_file_path1 = dir1.join("validators.txt");
        assert!(
            fs::metadata(&validators_txt_file_path1).is_ok(),
            "File not found, path: {:?}",
            &validators_txt_file_path1
        );
        let mut file = fs::File::open(&validators_txt_file_path1).unwrap();
        let mut contents = String::new();
        file.read_to_string(&mut contents).unwrap();
        assert_eq!(
            contents, "[validators]\npub_key2",
            "Contents were not generated correctly"
        );

        // check if the files for the second validator are created
        let dir2 = docker_network
            .get_generated_network_root()
            .join("validators")
            .join("validator_1")
            .join("config");
        assert!(
            fs::metadata(dir2.join("ledger.json")).is_ok(),
            "File not found, path: {:?}",
            dir2.join("ledger.json")
        );
        assert!(
            fs::metadata(dir2.join("rippled.cfg")).is_ok(),
            "File not found, path: {:?}",
            dir2.join("rippled.cfg")
        );
        let validators_txt_file_path2 = dir2.join("validators.txt");
        assert!(
            fs::metadata(&validators_txt_file_path2).is_ok(),
            "File not found, path: {:?}",
            &validators_txt_file_path2
        );
        let mut file = fs::File::open(&validators_txt_file_path2).unwrap();
        let mut contents = String::new();
        file.read_to_string(&mut contents).unwrap();
        assert_eq!(
            contents, "[validators]\npub_key1",
            "Contents were not generated correctly"
        );
    }

    // Note: This test requires running a docker engine in clean state and the controller to be running
    // Tests the initialize_network function; assert that the network is correctly initialized with the correct amount of nodes and names.
    // Also tests the stop_network function
    #[tokio::test]
    // #[coverage(off)]  // Only available in nightly build, don't forget to uncomment #![feature(coverage_attribute)] on line 1 of main
    async fn test_initialize_network() {
        let mut docker_network = docker_network_setup();
        assert_eq!(
            docker_network
                .docker
                .list_containers::<String>(None)
                .await
                .unwrap()
                .len(),
            0,
            "This test requires a clean docker starting state"
        );
        let client = match packet_client::PacketClient::new().await {
            Ok(client) => client,
            error => panic!("Error creating client: {:?}", error),
        };
        docker_network.initialize_network(client).await;
        assert_eq!(
            docker_network.containers.len(),
            3,
            "Not all containers were started"
        );

        let running_containers = docker_network
            .docker
            .list_containers::<String>(None)
            .await
            .unwrap();
        assert_eq!(
            running_containers.len(),
            3,
            "Not all containers were started"
        );

        let re = regex::Regex::new(r"^/validator_\d+$").unwrap();
        for container in running_containers {
            if let Some(names) = container.names {
                for name in names {
                    assert!(
                        re.is_match(&name),
                        "Container name does not match expected pattern: {}",
                        name
                    );
                }
            }
        }

        docker_network.stop_network().await;
        assert_eq!(
            docker_network
                .docker
                .list_containers::<String>(None)
                .await
                .unwrap()
                .len(),
            0,
            "Docker containers were not stopped correctly"
        );
    }
}
