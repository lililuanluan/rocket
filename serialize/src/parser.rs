use json::{object, JsonValue};
use lazy_static::lazy_static;
use nom::branch::alt;
use nom::bytes::complete::take;
use nom::combinator::{fail, map, rest, success, value, verify};
use nom::error::Error;
use nom::multi::{length_value, many0};
use nom::number::complete::{be_u16, be_u32, be_u64, be_u8};
use nom::sequence::{pair, preceded, tuple};
use nom::{bits, IResult};
use std::collections::HashMap;
use std::convert::TryFrom;
use std::fs::File;
use std::io::Read;

lazy_static! {
    static ref MAPPING: HashMap<FieldType, FieldInformation> = read_from_file();
}

fn decode_type_code(type_code: u8) -> &'static str {
    match type_code {
        0 => "NotPresent",
        1 => "UInt16",
        2 => "UInt32",
        3 => "UInt64",
        5 => "Hash256",
        6 => "Amount",
        7 => "Blob",
        8 => "AccountID",
        14 => "STObject",
        19 => "Vector256",
        _ => "Unknown",
    }
}

fn decode_field_code(field_type: &str, field_code: u8) -> String {
    let fields = &MAPPING;
    let current_key = FieldType {
        nth: field_code,
        type_field: field_type.to_string(),
    };
    let result = match fields.get(&current_key) {
        Some(field) => field.field_name.to_string(),
        None => "Unknown".to_string(),
    };
    // if the key is not in the fields in definitions.json
    if result.eq("Unknown") {
        return match (field_type, field_code) {
            ("UInt64", 10) => "Cookie".to_string(),
            ("Hash256", 25) => "ValidatedHash".to_string(),
            _ => "Unknown".to_string(),
        };
    }
    result
}

fn field_id(input: &[u8]) -> IResult<&[u8], (u8, u8)> {
    // let next_byte = &;
    let (input, (high, low)) = bits::<_, _, Error<(&[u8], usize)>, _, _>(pair(
        bits::complete::take(4usize),
        bits::complete::take(4usize),
    ))(input)?;
    match (high != 0, low != 0) {
        (true, true) => value((high, low), success(0))(input),
        (true, false) => pair(value(high, success(0)), map(take(1usize), |x: &[u8]| x[0]))(input),
        (false, true) => pair(map(take(1usize), |x: &[u8]| x[0]), value(low, success(0)))(input),
        (false, false) => pair(
            map(take(1usize), |x: &[u8]| x[0]),
            map(take(1usize), |x: &[u8]| x[0]),
        )(input),
    }
}

fn parse_fail(input: &[u8]) -> IResult<&[u8], JsonValue> {
    map(fail, |n: u16| JsonValue::Number(n.into()))(input)
}

fn parse_uint16(input: &[u8]) -> IResult<&[u8], JsonValue> {
    map(be_u16, |n: u16| JsonValue::Number(n.into()))(input)
}

fn parse_uint32(input: &[u8]) -> IResult<&[u8], JsonValue> {
    map(be_u32, |n: u32| JsonValue::Number(n.into()))(input)
}

fn parse_uint64(input: &[u8]) -> IResult<&[u8], JsonValue> {
    map(be_u64, |n: u64| JsonValue::Number(n.into()))(input)
}

fn parse_hash256(input: &[u8]) -> IResult<&[u8], JsonValue> {
    map(take(32usize), |hash: &[u8]| {
        JsonValue::String(hex::encode(hash))
    })(input)
}

fn parse_length_1_byte(input: &[u8]) -> IResult<&[u8], u32> {
    map(verify(be_u8, |n: &u8| *n <= 192), |n: u8| n as u32)(input)
}

fn parse_length_2_bytes(input: &[u8]) -> IResult<&[u8], u32> {
    let formula = |(x, y): (u8, u8)| 193 + (((x as u32) - 193) * 256) + (y as u32);
    map(pair(verify(be_u8, |n: &u8| *n <= 240), be_u8), formula)(input)
}

fn parse_length_3_bytes(input: &[u8]) -> IResult<&[u8], u32> {
    let formula = |(x, y, z): (u8, u8, u8)| {
        12481 + (((x as u32) - 241) * 65536) + ((y as u32) * 256) + (z as u32)
    };
    map(tuple((be_u8, be_u8, be_u8)), formula)(input)
}

fn parse_length(input: &[u8]) -> IResult<&[u8], u32> {
    alt((
        parse_length_1_byte,
        parse_length_2_bytes,
        parse_length_3_bytes,
    ))(input)
}

fn parse_blob(input: &[u8]) -> IResult<&[u8], JsonValue> {
    length_value(
        parse_length,
        map(rest, |x: &[u8]| JsonValue::String(hex::encode(x))),
    )(input)
}

fn parse_amount(input: &[u8]) -> IResult<&[u8], JsonValue> {
    map(be_u64, |n: u64| {
        JsonValue::String((n ^ 0x4000000000000000).to_string())
    })(input)
}

fn parse_account_id(input: &[u8]) -> IResult<&[u8], JsonValue> {
    map(preceded(take(1usize), take(20usize)), |address: &[u8]| {
        JsonValue::String(ripple_address_codec::encode_account_id(
            <&[u8; 20]>::try_from(address).unwrap(),
        ))
    })(input)
}

fn parse_field(input: &[u8]) -> IResult<&[u8], (String, JsonValue)> {
    let (input, (type_code, field_code)) = field_id(input)?;
    let type_str = decode_type_code(type_code);
    let field_name = decode_field_code(type_str, field_code);
    pair(
        value(field_name, success(0)),
        match type_str {
            "UInt16" => parse_uint16,
            "UInt32" => parse_uint32,
            "UInt64" => parse_uint64,
            "Hash256" => parse_hash256,
            "Blob" => parse_blob,
            "Amount" => parse_amount,
            "AccountID" => parse_account_id,
            _ => parse_fail,
        },
    )(input)
}

pub fn parse(input: &[u8]) -> IResult<&[u8], JsonValue> {
    let (input, values) = many0(parse_field)(input)?;
    let mut json = object! {};
    for (k, v) in values {
        json[k] = v;
    }
    Ok((input, json))
}

fn read_from_file() -> HashMap<FieldType, FieldInformation> {
    let mut data = String::new();
    
    // 尝试多个可能的路径
    let possible_paths = [
        "src/deserialization/definitions.json",
        "serialize/src/deserialization/definitions.json",
        "./src/deserialization/definitions.json",
        // 当作为Python模块运行时，可能在不同的工作目录
        concat!(env!("CARGO_MANIFEST_DIR"), "/src/deserialization/definitions.json"),
    ];
    
    let mut file = None;
    for path in &possible_paths {
        if let Ok(f) = File::open(path) {
            file = Some(f);
            break;
        }
    }
    
    let mut file = file.expect(&format!(
        "Could not find definitions.json in any expected location. Tried: {:?}",
        possible_paths
    ));
    file.read_to_string(&mut data)
        .expect("Reading from file did not work.");

    let all_values: serde_json::Value =
        serde_json::from_str(&data).expect("Parsing the data did not work.");
    // get only the fields
    let fields = serde_json::json!(all_values["FIELDS"]);

    // hashmap with all the fields (key: nth + type)
    let mut all_fields = HashMap::new();

    for field in fields.as_array().unwrap() {
        // the array of each field in the JSON
        let current_field = field[1].as_object().unwrap();
        
        // Skip fields that are not serialized (they won't appear in actual messages)
        let is_serialized = current_field["isSerialized"].as_bool().unwrap();
        if !is_serialized {
            continue;
        }
        
        let nth = current_field["nth"].as_u64().unwrap();
        // Skip fields with nth > 255 (can't fit in u8)
        if nth > 255 {
            continue;
        }
        
        // key: nth + type
        let current_key = FieldType {
            nth: nth as u8,
            type_field: current_field["type"].to_string().replace('\"', ""),
        };
        let current_value = FieldInformation {
            // field name
            field_name: field[0].to_string().replace('\"', ""),
            // isVLEncoded
            is_vl_encoded: current_field["isVLEncoded"].as_bool().unwrap(),
            // isSerialized
            is_serialized,
            // isSigningField
            is_signing_field: current_field["isSigningField"].as_bool().unwrap(),
        };
        all_fields.insert(current_key, current_value);
    }

    all_fields
}

#[derive(PartialEq, Eq, Hash)]
pub struct FieldType {
    pub nth: u8,
    pub type_field: String,
}

impl FieldType {
    #[allow(unused)]
    pub fn new(nth: u8, type_field: String) -> Self {
        FieldType { nth, type_field }
    }
}

pub struct FieldInformation {
    pub field_name: String,
    pub is_vl_encoded: bool,
    pub is_serialized: bool,
    pub is_signing_field: bool,
}

impl FieldInformation {
    #[allow(unused)]
    pub fn new(
        field_name: String,
        is_vl_encoded: bool,
        is_serialized: bool,
        is_signing_field: bool,
    ) -> Self {
        FieldInformation {
            field_name,
            is_vl_encoded,
            is_serialized,
            is_signing_field,
        }
    }
}

// Serialization functions - reverse of parse functions

fn encode_type_code(type_name: &str) -> Option<u8> {
    match type_name {
        "NotPresent" => Some(0),
        "UInt16" => Some(1),
        "UInt32" => Some(2),
        "UInt64" => Some(3),
        "Hash256" => Some(5),
        "Amount" => Some(6),
        "Blob" => Some(7),
        "AccountID" => Some(8),
        "STObject" => Some(14),
        "Vector256" => Some(19),
        _ => None,
    }
}

fn encode_field_code(field_name: &str) -> Option<(u8, u8)> {
    // Handle alias: "hash" maps to "LedgerHash" 
    let actual_field_name = if field_name == "hash" {
        "LedgerHash"
    } else {
        field_name
    };
    
    let fields = &MAPPING;
    
    // Debug: print first few fields
    if actual_field_name == "LedgerHash" {
        // eprintln!("DEBUG: Looking for 'LedgerHash'");
        
        // Try to find it directly
        let test_key = FieldType {
            nth: 1,
            type_field: "Hash256".to_string(),
        };
        if let Some(value) = fields.get(&test_key) {
            // eprintln!("DEBUG: ✓ Direct lookup found: '{}'", value.field_name);
        } else {
            // eprintln!("DEBUG: ✗ Direct lookup for (Hash256, 1) failed!");
        }
        
        // Sample some fields
        let mut count = 0;
        for (key, value) in fields.iter() {
            if key.type_field == "Hash256" {
                // eprintln!("DEBUG:   Hash256 field: '{}' (nth: {})", value.field_name, key.nth);
                count += 1;
                if count > 5 { break; }
            }
        }
    }
    
    for (key, value) in fields.iter() {
        if value.field_name == actual_field_name {
            return Some((encode_type_code(&key.type_field)?, key.nth));
        }
    }
    
    // Special cases not in definitions.json
    match actual_field_name {
        "Cookie" => Some((3, 10)), // UInt64 = 3, field code 10
        "ValidatedHash" => Some((5, 25)), // Hash256 = 5, field code 25
        _ => {
            // eprintln!("DEBUG: encode_field_code failed for '{}' (mapped to '{}')", field_name, actual_field_name);
            None
        }
    }
}

fn encode_field_id(type_code: u8, field_code: u8) -> Vec<u8> {
    match (type_code < 16, field_code < 16) {
        (true, true) => {
            // Both fit in 4 bits - encode in one byte
            vec![(type_code << 4) | field_code]
        }
        (true, false) => {
            // Type fits in 4 bits, field doesn't
            vec![type_code << 4, field_code]
        }
        (false, true) => {
            // Field fits in 4 bits, type doesn't
            vec![field_code, type_code]
        }
        (false, false) => {
            // Neither fits in 4 bits
            vec![0, type_code, field_code]
        }
    }
}

fn encode_length(length: u32) -> Vec<u8> {
    if length <= 192 {
        vec![length as u8]
    } else if length <= 12480 {
        let adjusted = length - 193;
        let high = (adjusted / 256) as u8 + 193;
        let low = (adjusted % 256) as u8;
        vec![high, low]
    } else {
        let adjusted = length - 12481;
        let high = (adjusted / 65536) as u8 + 241;
        let mid = ((adjusted % 65536) / 256) as u8;
        let low = (adjusted % 256) as u8;
        vec![high, mid, low]
    }
}

pub fn serialize(json_value: &JsonValue) -> Result<Vec<u8>, String> {
    let mut result = Vec::new();
    
    if !json_value.is_object() {
        return Err("Input must be a JSON object".to_string());
    }
    
    // Define field order for proper serialization
    // Note: Parser may return "hash" or "LedgerHash" depending on version
    let field_order = [
        "Flags",
        "LedgerSequence", 
        "SigningTime",
        "Cookie",
        "LedgerHash",     // Try LedgerHash first, then fall back to "hash"
        "ConsensusHash",
        "ValidatedHash",
        "SigningPubKey",
        "Signature",
    ];
    
    for field_name in &field_order {
        // Check if field exists in the JSON object
        // For LedgerHash, also try "hash" as fallback
        let value = if json_value[*field_name].is_null() {
            if *field_name == "LedgerHash" && !json_value["hash"].is_null() {
                &json_value["hash"]
            } else {
                continue;
            }
        } else {
            &json_value[*field_name]
        };
        
        // Get type and field codes (encode_field_code handles the hash->LedgerHash mapping)
        let (type_code, field_code) = encode_field_code(field_name)
            .ok_or_else(|| format!("Unknown field: {}", field_name))?;
        
        // Encode field ID
        result.extend(encode_field_id(type_code, field_code));
        
        // Encode value based on type
        let type_str = decode_type_code(type_code);
        match type_str {
            "UInt16" => {
                let num = value.as_u16()
                    .ok_or_else(|| format!("Field {} must be UInt16", field_name))?;
                result.extend(&num.to_be_bytes());
            }
            "UInt32" => {
                let num = value.as_u32()
                    .ok_or_else(|| format!("Field {} must be UInt32", field_name))?;
                result.extend(&num.to_be_bytes());
            }
            "UInt64" => {
                let num = value.as_u64()
                    .ok_or_else(|| format!("Field {} must be UInt64", field_name))?;
                result.extend(&num.to_be_bytes());
            }
            "Hash256" => {
                let hash_str = value.as_str()
                    .ok_or_else(|| format!("Field {} must be a string", field_name))?;
                let hash_bytes = hex::decode(hash_str)
                    .map_err(|e| format!("Invalid hex string for {}: {}", field_name, e))?;
                if hash_bytes.len() != 32 {
                    return Err(format!("Hash256 field {} must be 32 bytes", field_name));
                }
                result.extend(hash_bytes);
            }
            "Blob" => {
                let blob_str = value.as_str()
                    .ok_or_else(|| format!("Field {} must be a string", field_name))?;
                let blob_bytes = hex::decode(blob_str)
                    .map_err(|e| format!("Invalid hex string for {}: {}", field_name, e))?;
                result.extend(encode_length(blob_bytes.len() as u32));
                result.extend(blob_bytes);
            }
            "Amount" => {
                let amount_str = value.as_str()
                    .ok_or_else(|| format!("Field {} must be a string", field_name))?;
                let amount: u64 = amount_str.parse()
                    .map_err(|e| format!("Invalid amount for {}: {}", field_name, e))?;
                let encoded_amount = amount ^ 0x4000000000000000;
                result.extend(&encoded_amount.to_be_bytes());
            }
            "AccountID" => {
                let account_str = value.as_str()
                    .ok_or_else(|| format!("Field {} must be a string", field_name))?;
                let decoded = ripple_address_codec::decode_account_id(account_str)
                    .map_err(|e| format!("Invalid account ID for {}: {}", field_name, e))?;
                result.push(20); // Length prefix
                result.extend(&decoded);
            }
            _ => {
                return Err(format!("Unsupported type {} for field {}", type_str, field_name));
            }
        }
    }
    
    Ok(result)
}
