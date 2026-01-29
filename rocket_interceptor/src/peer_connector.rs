//! This module is responsible for setting up connections between peers.

use base64::engine::general_purpose;
use base64::Engine;
use basex_rs::{BaseX, ALPHABET_RIPPLE};
use bytes::BytesMut;
use log::{debug, error, info, warn};
use openssl::sha::Sha512;
use openssl::ssl::{Ssl, SslContext, SslMethod};
use secp256k1::{Message as CryptoMessage, Secp256k1, SecretKey};
use std::net::{IpAddr, SocketAddr};
use std::path::Path;
use std::pin::Pin;
use std::str::FromStr;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::time::timeout;
use tokio_openssl::SslStream;

/// Struct that represents the object that connects peers with each other.
#[derive(Clone)]
pub struct PeerConnector {
    /// The IP address of every peer. Only the ports of the peers differ.
    pub ip_addr: String,
}

impl PeerConnector {
    /// Initializes a new PeerConnector.
    ///
    /// # Parameters
    /// * 'ip_addr' - the IP address of all peers.
    pub fn new(ip_addr: String) -> Self {
        Self { ip_addr }
    }

    /// Connects two peers with each other. Returns both halves of the connection, so the interceptor is in between.
    ///
    /// # Parameters
    /// * 'port_peer_1' - the port of the first peer.
    /// * 'port_peer_2' - the port of the second peer.
    /// * 'pub_key_peer_1' - the public key of the first peer.
    /// * 'pub_key_peer_2' - the public key of the second peer.
    /// * 'seed_peer_1' - the validation seed of the first peer.
    /// * 'seed_peer_2' - the validation seed of the second peer.
    pub async fn connect_peers(
        &self,
        port_peer_1: u16,
        port_peer_2: u16,
        pub_key_peer_1: &str,
        pub_key_peer_2: &str,
        seed_peer_1: &str,
        seed_peer_2: &str,
    ) -> Result<(SslStream<TcpStream>, SslStream<TcpStream>), String> {
        // Try to establish both halves and propagate errors to the caller so the caller
        // can decide whether to skip this pair.
        let connection_half_1 = Self::setup_connection_half(
            self.ip_addr.as_str(),
            port_peer_1,
            pub_key_peer_2,
            seed_peer_2,
        )
        .await?;
        let connection_half_2 = Self::setup_connection_half(
            self.ip_addr.as_str(),
            port_peer_2,
            pub_key_peer_1,
            seed_peer_1,
        )
        .await?;
        Ok((connection_half_1, connection_half_2))
    }

    /// Sets up a connection half from a peer to another peer.
    /// Connects to the peer at ip:port.
    /// We pretend to be the other peer with its public key.
    /// This way we can intercept the connection.
    ///
    /// # Parameters
    /// * 'ip' - the ip to which we connect to.
    /// * 'port' - the port to which we connect to.
    /// * 'initiator_public_key' - the public key of the peer we pretend to be.
    /// * 'initiator_seed' - the validation seed of the peer we pretend to be.
    ///
    /// # Panics
    /// * If an error occurred while creating and connecting the SslStream.
    /// * If an error occurred while reading or writing to/from the SslStream.
    /// * If the response of the upgrade request is invalid.
    async fn setup_connection_half(
        ip: &str,
        port: u16,
        initiator_public_key: &str,
        initiator_seed: &str,
    ) -> Result<SslStream<TcpStream>, String> {
        // Try default token selection first
        let mut ssl_stream = Self::create_and_connect_ssl_stream(
            ip,
            port,
            initiator_public_key,
            initiator_seed,
        )
        .await
        .map_err(|e| format!("Failed to create/connect SSL stream: {}", e))?;

        // Read until we see end of HTTP headers ("\r\n\r\n") or hit limits. This avoids
        // panics when the TCP stream returns a split header in the first read.
        let mut buf = BytesMut::new();
        let mut attempts = 0;
        // read until we see end of HTTP headers ("\r\n\r\n") or reach attempts/size limits
        loop {
            let mut vec = vec![0; 4096];
            // read with a per-attempt timeout to avoid long blocking
            match timeout(Duration::from_secs(5), ssl_stream.read(&mut vec)).await {
                Ok(Ok(size)) => {
                    if size == 0 {
                        error!("Handshake read returned EOF. Current buffer: {}", String::from_utf8_lossy(&buf).trim());
                        return Err("Socket closed by peer during handshake".to_string());
                    }
                    vec.resize(size, 0);
                    buf.extend_from_slice(&vec);
                }
                Ok(Err(e)) => {
                    error!("Unable to read handshake response: {}", e);
                    return Err(format!("Unable to read handshake response: {}", e));
                }
                Err(_) => {
                    // timeout
                    warn!("Timed out waiting for handshake bytes from {}:{} (attempt {})", ip, port, attempts);
                    attempts += 1;
                    if attempts > 8 {
                        return Err("Timeout while reading handshake response".to_string());
                    }
                    if buf.len() > 16 * 1024 {
                        return Err("Handshake buffer too large or incomplete after timeouts".to_string());
                    }
                    continue;
                }
            }

            // Stop reading when we have the headers terminator
            if buf.windows(4).position(|x| x == b"\r\n\r\n").is_some() {
                break;
            }
            attempts += 1;
            if attempts > 8 || buf.len() > 16 * 1024 {
                // give up and try to parse what we have
                break;
            }
        }

        if let Err(e) = Self::check_upgrade_request_response(buf.clone()) {
            // Log and return error so caller can skip this pair; avoid panicking.
            // Dump server response headers/body to help debugging.
            let response_str = String::from_utf8_lossy(&buf).to_string();
            error!("Handshake failed: {}; server response: {}", e, response_str);
            return Err(e);
        }

        Ok(ssl_stream)
    }

    /// This method checks given a buffered HTTP response, whether it is a valid 101 switching protocol response.
    ///
    /// # Panics
    /// * If it could not parse the response.
    /// * If it received a partial message.
    /// * If it could not separate the HTTP headers from the body.
    /// * If the response code is not '101' as expected to be.
    fn check_upgrade_request_response(buffered_response: BytesMut) -> Result<(), String> {
        // Very small, robust check: ensure headers end exists and status code is 101
        if let Some(n) = buffered_response.windows(4).position(|x| x == b"\r\n\r\n") {
            let header_bytes = &buffered_response[0..n + 4];
            if let Ok(headers) = std::str::from_utf8(header_bytes) {
                if let Some(first_line) = headers.lines().next() {
                    let parts: Vec<&str> = first_line.split_whitespace().collect();
                    if parts.len() >= 2 {
                        if parts[1] == "101" {
                            return Ok(());
                        } else {
                            return Err(format!("Expected 101 switching protocols, got {}", parts[1]));
                        }
                    }
                }
            }
            Err("Parsing response failed".to_string())
        } else {
            Err("Could not separate HTTP headers from body.".to_string())
        }
    }

    /// Creates a SslStream and connects to the specified IP address + port.
    ///
    /// # Parameters
    /// * 'ip' - the IP address to which a connection should be made.
    /// * 'port' - the port to which a connection should be made.
    /// * 'public_key' - the public key of the node initiating the connection.
    /// * 'seed' - the validation seed of the node initiating the connection.
    ///
    /// # Panics
    /// * If the ip:port specified is invalid.
    /// * If the SslStream could not be created or connected to.
    async fn create_and_connect_ssl_stream(
        ip: &str,
        port: u16,
        public_key: &str,
        seed: &str,
    ) -> Result<SslStream<TcpStream>, String> {
        let socket_address = SocketAddr::new(
            IpAddr::from_str(ip).map_err(|e| format!("Invalid IP: {}", e))?,
            port,
        );
        let tcp_stream = TcpStream::connect(socket_address)
            .await
            .map_err(|e| format!("TCP connect failed: {}", e))?;

        tcp_stream
            .set_nodelay(true)
            .map_err(|e| format!("Enable TCP_NODELAY failed: {}", e))?;
        let ssl_context = SslContext::builder(SslMethod::tls())
            .map_err(|e| format!("Create SSL context failed: {}", e))?
            .build();
        let ssl_session = Ssl::new(&ssl_context).map_err(|e| format!("Create SSL session failed: {}", e))?;
        let mut ssl_stream = SslStream::<TcpStream>::new(ssl_session, tcp_stream)
            .map_err(|e| format!("Create SSL stream failed: {}", e))?;
        SslStream::connect(Pin::new(&mut ssl_stream))
            .await
            .map_err(|e| format!("SSL connection failed: {}", e))?;

        // The following block of code is responsible for computing the Session-Signature
        // for the Handshake, which is required to establish a connection between two nodes.
        // See https://github.com/XRPLF/rippled/blob/f64cf9187affd69650907d0d92e097eb29693945/src/xrpld/overlay/detail/Handshake.cpp#L199-L203
        // for the original implementation by the XRPLF.
        let ssl_ref = ssl_stream.ssl();
        let mut buf = vec![0; 1024];

        // Get the contents of the last message sent to the peer.
        let mut size1 = ssl_ref.finished(&mut buf[..]);
        if size1 > buf.len() {
            buf.resize(size1, 0);
            size1 = ssl_ref.finished(&mut buf[..]);
        }
        // Hash the finished message
        let mut ctx_sha512_message1 = Sha512::new();
        ctx_sha512_message1.update(&buf[..size1]);
        let message1_hash = &ctx_sha512_message1.finish();
        debug!("Finished message SHA512: {:?}", message1_hash);

        // Get the contents of the last received message from the peer.
        let mut size2 = ssl_ref.peer_finished(&mut buf[..]);
        if size2 > buf.len() {
            buf.resize(size2, 0);
            size2 = ssl_ref.peer_finished(&mut buf[..]);
        }
        // Hash the received message
        let mut ctx_sha512_message2 = Sha512::new();
        ctx_sha512_message2.update(&buf[..size2]);
        let message2_hash = &ctx_sha512_message2.finish();
        debug!("Received message SHA512: {:?}", message2_hash);

        // XOR the contents of both finished messages
        let message_xor = message1_hash
            .iter()
            .zip(message2_hash.iter())
            .map(|(a, b)| a ^ b)
            .collect::<Vec<u8>>();
        debug!("XOR of messages: {:?}", message_xor);

        let mut ctx_sha512_xor = Sha512::new();
        ctx_sha512_xor.update(&message_xor[..]);
        let xor_hash = ctx_sha512_xor.finish();
        let msg = CryptoMessage::from_digest_slice(&xor_hash[0..32])
            .map_err(|e| format!("Failed to create crypto message from xor hash: {}", e))?;

        let mut seed_bytes = if let Some(b) = BaseX::with_alphabet(ALPHABET_RIPPLE)
            .from_bs58(&String::from(seed))
        {
            b
        } else {
            return Err(format!("Failed to base58-decode seed"));
        };
        let mut ctx_sha512_seed = Sha512::new();

        // Set last 4 bytes (bytes 18-21) to 0
        // These bytes are the "Root key sequence", and signify how many times the key had to
        // be regenerated before being a valid secp256k1 secret key. Anything over 0 is highly
        // unlikely, thus hardcoded here. If not set to zero, they seem to take on a random value,
        // which causes the signature to become invalid.
        // https://xrpl.org/docs/concepts/accounts/cryptographic-keys#secp256k1-key-derivation
        seed_bytes[17] = 0u8;
        seed_bytes[18] = 0u8;
        seed_bytes[19] = 0u8;
        seed_bytes[20] = 0u8;

        ctx_sha512_seed.update(&seed_bytes[1..]);
        let seed_hash = ctx_sha512_seed.finish();
    let secp256k1_ctx = Secp256k1::new();
    let sk = SecretKey::from_slice(&seed_hash[..32]).map_err(|e| format!("Failed to create secret key: {}", e))?;
    let sig = secp256k1_ctx.sign_ecdsa(&msg, &sk).serialize_der();
        let b64sig = general_purpose::STANDARD.encode(sig);

        // Determine which Upgrade token to send based on local config 'image' (1.4.0 -> RTXP/1.2, else XRPL/2.2)
        let mut upgrade_token = "XRPL/2.2";
        if let Some(image) = crate::docker_manager::get_image_from_config_file(Path::new("config.yaml")) {
            // Inspect the image tag (the part after the last ':'). If it starts with "1.",
            // treat it as rippled 1.x and use the RTXP/1.2 token.
            let tag = image.rsplit(':').next().unwrap_or(&image);
            if tag.starts_with("1.") {
                upgrade_token = "RTXP/1.2";
            }
        }

        let content = Self::format_upgrade_request_content(upgrade_token, public_key, b64sig.as_str());

        // Log the outgoing Upgrade request (redact Session-Signature for safety)
        {
            let mut debug_content = content.clone();
            if let Some(start) = debug_content.find("Session-Signature:") {
                // find end of the line
                if let Some(end_rel) = debug_content[start..].find("\r\n") {
                    let end = start + end_rel;
                    // replace the signature payload with a redaction marker
                    debug_content.replace_range(start..end, "Session-Signature: <redacted>");
                }
            }
            debug!("Sending Upgrade request (redacted): {}", debug_content.lines().take(6).collect::<Vec<&str>>().join("\n"));
        }

        ssl_stream
            .write_all(content.as_bytes())
            .await
            .map_err(|e| format!("Could not send handshake request: {}", e))?;

        Ok(ssl_stream)
    }

    /// Creates a request message which will upgrade the connection between peer and interceptor.
    fn format_upgrade_request_content(upgrade_token: &str, public_key: &str, base64_sig: &str) -> String {
        format!(
            "GET / HTTP/1.1\r\nUser-Agent: rocket-interceptor\r\nUpgrade: {}\r\nConnection: Upgrade\r\nConnect-As: Peer\r\nPublic-Key: {}\r\nSession-Signature: {}\r\n\r\n",
            upgrade_token, public_key, base64_sig
        )
    }
}

#[cfg(test)]
mod unit_tests {
    use crate::peer_connector::PeerConnector;
    use bytes::BytesMut;

    #[test]
    // #[coverage(off)]  // Only available in nightly build, don't forget to uncomment #![feature(coverage_attribute)] on line 1 of main
    fn peer_connector_new_test() {
        let peer_connector = PeerConnector::new("127.0.0.1".to_string());
        assert_eq!(peer_connector.ip_addr, "127.0.0.1".to_string());
    }

    #[test]
    // #[coverage(off)]  // Only available in nightly build, don't forget to uncomment #![feature(coverage_attribute)] on line 1 of main
    fn upgrade_request_test() {
        let expected = String::from("GET / HTTP/1.1\r\nUser-Agent: rocket-interceptor\r\nUpgrade: XRPL/2.2\r\nConnection: Upgrade\r\nConnect-As: Peer\r\nPublic-Key: 123456789abcdefg\r\nSession-Signature: 123456789abcdefg\r\n\r\n");
        assert_eq!(expected, PeerConnector::format_upgrade_request_content("XRPL/2.2", "123456789abcdefg", "123456789abcdefg"))
    }

    #[test]
    // #[coverage(off)]  // Only available in nightly build, don't forget to uncomment #![feature(coverage_attribute)] on line 1 of main
    fn check_upgrade_request_response_no_panic() {
        let response = b"\
            HTTP/1.1 101 Switching Protocol\r\n
            Connection: Upgrade\r\n\
            Upgrade: XRPL/2.2\r\n
            Connect-As: Peer\r\n
            Server: rippled-2.1.1\r\n
            Crawl: private\r\n
            X-Protocol-Ctl:\r\n
            Network-Time: 770391649\r\n
            Public-Key: n9M1Fh52PBMSrEjjs8Y64EmU8hfVzb29BBDaXoVNS3AaC1gM19CP\r\n
            Session-Signature: MEUCIQCBsA3JThSv4geQ67ZlrLvBZGO0wiWWU5pfDsiKalvwKQIgb6CuAHAYnxGf4MYB4Jgsbox4of5GxT4IbRPWablVQ9w=\r\n\
            Instance-Cookie: 16110088623413850902\r\n
            Closed-Ledger: 2D7DE9661AADBCDC6DD6630F0C616F5BE29803A5A5DC31486DD65E0F6A79DDB1\r\n
            Previous-Ledger: 0000000000000000000000000000000000000000000000000000000000000000\r\n\r\n
        ";

        let mut buffer = BytesMut::new();
        buffer.extend_from_slice(response);
        assert!(PeerConnector::check_upgrade_request_response(buffer).is_ok());
    }

    #[test]
    // #[coverage(off)]  // Only available in nightly build, don't forget to uncomment #![feature(coverage_attribute)] on line 1 of main
    fn check_upgrade_request_response_invalid_request() {
        let mut buffer = BytesMut::new();
        buffer.extend_from_slice(b"garbage\r\n\r\n");
        let res = PeerConnector::check_upgrade_request_response(buffer);
        assert!(res.is_err());
        assert_eq!(res.unwrap_err(), "Parsing response failed");
    }

    #[test]
    // #[coverage(off)]  // Only available in nightly build, don't forget to uncomment #![feature(coverage_attribute)] on line 1 of main
    fn check_upgrade_request_response_invalid_response() {
         let mut buffer = BytesMut::new();
         let data = vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
         buffer.extend_from_slice(&data);
         let res = PeerConnector::check_upgrade_request_response(buffer);
         assert!(res.is_err());
         assert_eq!(res.unwrap_err(), "Could not separate HTTP headers from body.");
     }

    #[test]
    // #[coverage(off)]  // Only available in nightly build, don't forget to uncomment #![feature(coverage_attribute)] on line 1 of main
    fn check_upgrade_request_response_wrong_status_code() {
         let mut buf = BytesMut::new();
         buf.extend_from_slice(b"HTTP/1.1 404 Not Found\r\n\r\n<body message>");

         let res = PeerConnector::check_upgrade_request_response(buf);
         assert!(res.is_err());
         assert!(res.unwrap_err().starts_with("Expected 101 switching protocols, got 404"));
     }
 }
