# This is the main script for Hive Explorer.
import json
import requests

HIVE_API_URL = "https://api.hive.blog"

# Will be initialized by build_nai_map() later
NAI_MAP = {}

def build_nai_map():
    """
    Builds a map of NAI codes to (symbol, precision) tuples.
    Starts with native Hive assets and tries to fetch SMT definitions.
    """
    native_token_definitions = [
        {"nai": "@@000000021", "symbol": "HIVE", "precision": 3},
        {"nai": "@@000000013", "symbol": "HBD", "precision": 3},
        {"nai": "@@000000037", "symbol": "VESTS", "precision": 6}
    ]
    smt_definitions = []
    smt_fetch_failed = False

    try:
        payload = {
            "jsonrpc": "2.0",
            "method": "database_api.get_smt_tokens",
            "params": {},
            "id": 1
        }
        headers = {"Content-Type": "application/json"}
        # Add a timeout to prevent indefinite hanging
        response = requests.post(HIVE_API_URL, json=payload, headers=headers, timeout=5)
        response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
        response_json = response.json()

        if response_json.get('error'):
            smt_fetch_failed = True
            # Optional: Log the specific API error if needed for debugging, but don't print it as the primary user warning.
            # print(f"Debug: SMT API returned error: {response_json['error']}")
        elif isinstance(response_json.get('result'), list):
            smt_definitions = response_json['result']
            # Optional: print(f"Debug: Successfully fetched {len(smt_definitions)} SMT definitions.")
        else:
            # Unexpected successful response structure
            smt_fetch_failed = True
            # Optional: print(f"Debug: Unexpected SMT response structure: {response_json}")

    except Exception as e: # Catches requests.exceptions (timeout, connection error, HTTPError) & json.JSONDecodeError
        smt_fetch_failed = True
        # Optional: print(f"Debug: Exception during SMT fetch: {type(e).__name__} - {e}")

    if smt_fetch_failed:
        print("⚠️ SMT definitions not available or fetch failed; using HIVE, HBD, VESTS only.")

    all_definitions = native_token_definitions + smt_definitions
    final_nai_map = {}
    for token_def in all_definitions:
        if isinstance(token_def, dict):
            nai = token_def.get('nai')
            symbol = token_def.get('symbol')
            # Ensure precision is an int, default to 0 or handle as error if critical
            precision = token_def.get('precision')
            if isinstance(precision, int):
                pass # Precision is good
            elif isinstance(precision, str) and precision.isdigit():
                precision = int(precision) # Convert if string digit
            else: # Precision is missing or not a valid number
                print(f"⚠️ Skipping token definition due to invalid precision: {token_def}")
                continue

            if nai and symbol: # Symbol must also be present
                final_nai_map[nai] = (symbol, precision)
            else:
                print(f"⚠️ Skipping token definition due to missing NAI or symbol: {token_def}")
        else:
            print(f"⚠️ Skipping unexpected item in token definitions list: {token_def}")
    return final_nai_map

# Initialize NAI_MAP globally
NAI_MAP = build_nai_map()

# global NAI_MAP is populated by build_nai_map()
def format_asset(raw_asset_dict):
    if not (isinstance(raw_asset_dict, dict) and \
            'nai' in raw_asset_dict and \
            'amount' in raw_asset_dict and \
            'precision' in raw_asset_dict):
        # print(f"Debug: Malformed asset_dict (missing keys) in format_asset: {raw_asset_dict}")
        return str(raw_asset_dict)

    try:
        nai = raw_asset_dict['nai']
        # Amount can be int or str, ensure it's converted to int
        amount = int(str(raw_asset_dict['amount'])) 
        # Precision from op data should be int
        raw_op_precision = int(raw_asset_dict['precision']) 
    except (ValueError, TypeError) as e:
        # print(f"Debug: Error converting amount/precision in format_asset: {e} for {raw_asset_dict}")
        return str(raw_asset_dict) # Fallback for conversion errors

    # Get (symbol, canonical_precision) from NAI_MAP. 
    # If NAI not found, default to (raw_nai_string, raw_op_precision).
    # This makes 'display_symbol' the actual symbol or the NAI string,
    # and 'display_precision' the canonical or raw precision.
    display_symbol, display_precision = NAI_MAP.get(nai, (nai, raw_op_precision))

    # Optional: Warning for precision mismatch if NAI was found and its canonical precision differs
    # from the precision specified in the operation's data.
    if nai in NAI_MAP and raw_op_precision != display_precision:
        print(f"⚠️ Precision mismatch for {display_symbol} ({nai}): operation data has {raw_op_precision}, canonical is {display_precision}. Using canonical precision for display.")
    
    # Always use display_precision (which is canonical if NAI known, else raw) for calculation and formatting.
    value = amount / (10**display_precision)
    return f"{value:.{display_precision}f} {display_symbol}"

def get_block(block_num: int):
    """
    Fetches a specific block from the Hive blockchain.

    Args:
        block_num: The block number to fetch.

    Returns:
        A dictionary containing the block data, or None if an error occurs.
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "condenser_api.get_block",
        "params": [block_num],
        "id": 1
    }
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(HIVE_API_URL, json=payload, headers=headers)
        response.raise_for_status()  # Raise an exception for HTTP errors (4xx or 5xx)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching block {block_num}: {e}")
        return None

    try:
        response_json = response.json()
    except json.JSONDecodeError:
        print(f"Error decoding JSON response for block {block_num}")
        return None

    if 'error' in response_json:
        print(f"API error for block {block_num}: {response_json['error']}")
        return None

    if 'result' in response_json:
        return response_json['result']
    
    print(f"Unexpected API response for block {block_num}: {response_json}")
    return None

def get_account_history(account_name: str, limit: int = 100, start_from_op_index: int = -1):
    """
    Fetches the account history for a specific Hive account, supporting pagination.

    Args:
        account_name: The name of the account to fetch history for.
        limit: The maximum number of history items to retrieve per call (max 1000, default 100).
        start_from_op_index: The operation index to start fetching from. -1 for most recent.

    Returns:
        A list of account history items, or None if an error occurs.
    """
    # Ensure limit is within sensible bounds for a single API call.
    # The API itself caps at 1000, but smaller limits are common for pagination.
    if not (0 < limit <= 1000):
        print("Limit for a single history request must be between 1 and 1000.")
        # Consider returning None or raising an error for invalid limit for a single page
        return None # Or clamp: limit = max(1, min(limit, 1000))

    payload = {
        "jsonrpc": "2.0",
        "method": "account_history_api.get_account_history",
        "params": {
            "account": account_name,
            "start": start_from_op_index,
            "limit": limit
        },
        "id": 1
    }
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(HIVE_API_URL, json=payload, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Network error while fetching account history for {account_name}: {e}")
        return None

    try:
        response_json = response.json()
    except json.JSONDecodeError:
        print(f"Error decoding JSON response for account history {account_name}")
        return None

    if 'error' in response_json:
        print(f"API Error for account {account_name} history: {response_json['error']}")
        return None

    if 'result' in response_json and 'history' in response_json['result']:
        return response_json['result']['history']
    
    # Handle cases where 'result' might be the history list directly (less common for this API)
    # For now, strict check for 'history' key as per expected structure.
    # if 'result' in response_json and isinstance(response_json['result'], list):
    #     return response_json['result']

    print(f"Unexpected API response structure for account {account_name} history: {response_json}")
    return None

def format_operation(op_type: str, op_payload: dict) -> str:
    """
    Formats different Hive operation types into a human-readable string.

    Args:
        op_type: The type of the operation (e.g., "vote_operation").
        op_payload: The dictionary containing the operation's data.

    Returns:
        A formatted string representing the operation.
    """
    if not isinstance(op_payload, dict):
        return f"Invalid op_payload (not a dict): {str(op_payload)}"

    if op_type == "vote_operation":
        return f"[VOTE] {op_payload.get('voter','?')} → {op_payload.get('author','?')}/{op_payload.get('permlink','?')} @ {int(op_payload.get('weight', 0))/100:.2f}%"
    
    elif op_type == "effective_comment_vote_operation":
        payout_val = op_payload.get('pending_payout')
        payout_str = format_asset(payout_val) if isinstance(payout_val, dict) else str(payout_val)
        return f"[EFFECTIVE VOTE] {op_payload.get('voter','?')} on {op_payload.get('author','?')}/{op_payload.get('permlink','?')}, payout={payout_str}"

    elif op_type == "curation_reward_operation":
        reward_val = op_payload.get('reward')
        reward_str = format_asset(reward_val) if isinstance(reward_val, dict) else str(reward_val)
        comment_author = op_payload.get('comment_author','?')
        comment_permlink = op_payload.get('comment_permlink','?')
        base_str = f"[CURATION] {op_payload.get('curator','?')} earned {reward_str}"
        if comment_author != '?' and comment_permlink != '?': # Check against default '?'
            return f"{base_str} on {comment_author}/{comment_permlink}"
        return base_str

    elif op_type == "transfer_operation":
        amount_val = op_payload.get('amount')
        amount_str = format_asset(amount_val) if isinstance(amount_val, dict) else str(amount_val)
        return f"[TRANSFER] {op_payload.get('from','?')} → {op_payload.get('to','?')}: {amount_str} (memo={op_payload.get('memo', '')})"

    elif op_type == "author_reward_operation":
        hbd_payout_val = op_payload.get('hbd_payout')
        hive_payout_val = op_payload.get('hive_payout')
        vesting_payout_val = op_payload.get('vesting_payout')

        hbd_payout_str = format_asset(hbd_payout_val) if isinstance(hbd_payout_val, dict) else str(hbd_payout_val if hbd_payout_val is not None else '?')
        hive_payout_str = format_asset(hive_payout_val) if isinstance(hive_payout_val, dict) else str(hive_payout_val if hive_payout_val is not None else '?')
        vesting_payout_str = format_asset(vesting_payout_val) if isinstance(vesting_payout_val, dict) else str(vesting_payout_val if vesting_payout_val is not None else '?')
        
        return f"[AUTHOR REWARD] for {op_payload.get('author','?')}/{op_payload.get('permlink','?')}: HBD: {hbd_payout_str}, HIVE: {hive_payout_str}, VESTS: {vesting_payout_str}"

    elif op_type == "comment_operation":
        author = op_payload.get('author','?')
        permlink = op_payload.get('permlink','?')
        title = op_payload.get('title', '') # Title can be empty for comments
        parent_author = op_payload.get('parent_author', '')
        parent_permlink = op_payload.get('parent_permlink', '')
        body_snippet = op_payload.get('body', '')[:70].replace('\n', ' ') + "..."
        if not parent_author: 
            return f"[POST] by {author} - Title: '{title}', Permlink: {permlink}. Body: {body_snippet}"
        else: 
            return f"[COMMENT] by {author} on @{parent_author}/{parent_permlink} - Permlink: {permlink}. Body: {body_snippet}"

    elif op_type == "transfer_to_vesting_operation":
        amount_val = op_payload.get('amount')
        amount_str = format_asset(amount_val) if isinstance(amount_val, dict) else str(amount_val)
        from_acc = op_payload.get('from','?')
        to_acc = op_payload.get('to', '') or from_acc # If 'to' is empty, it's a self power-up
        return f"[POWER UP] by {from_acc} to {to_acc}, Amount: {amount_str}"

    elif op_type == "delegate_vesting_shares_operation":
        shares_val = op_payload.get('vesting_shares')
        shares_str = format_asset(shares_val) if isinstance(shares_val, dict) else str(shares_val)
        return f"[DELEGATE VESTS] from {op_payload.get('delegator','?')} to {op_payload.get('delegatee','?')}, Amount: {shares_str}"

    elif op_type == 'claim_reward_balance_operation':
        account = op_payload.get('account', '?')
        
        reward_hive_val = op_payload.get('reward_hive')
        reward_hbd_val = op_payload.get('reward_hbd')
        reward_vests_val = op_payload.get('reward_vests')

        r_hive = format_asset(reward_hive_val) if isinstance(reward_hive_val, dict) else str(reward_hive_val)
        r_hbd  = format_asset(reward_hbd_val) if isinstance(reward_hbd_val, dict) else str(reward_hbd_val)
        r_vest = format_asset(reward_vests_val) if isinstance(reward_vests_val, dict) else str(reward_vests_val)
        
        return f"[CLAIM REWARD] {account} claimed → HIVE: {r_hive}, HBD: {r_hbd}, VESTS: {r_vest}"

    elif op_type == "custom_json_operation":
        try:
            json_str = op_payload.get('json', '{}')
            if not isinstance(json_str, str):
                json_str = '{}' # Default to empty JSON if not a string
            data = json.loads(json_str)
            data_str = json.dumps(data, indent=2, ensure_ascii=False)
            indented_data_str = "\n".join(["    " + line for line in data_str.splitlines()])
            return f"[CUSTOM_JSON id={op_payload.get('id','?')}]\n{indented_data_str}"
        except json.JSONDecodeError:
            return f"[CUSTOM_JSON id={op_payload.get('id','?')}] Error decoding JSON: {op_payload.get('json', '')}"
        except Exception as e:
            return f"[CUSTOM_JSON id={op_payload.get('id','?')}] Error processing: {str(e)}"
            
    else:  # Fallback for other operation types
        return f"[{op_type.upper()}]\n{json.dumps(op_payload, indent=2, ensure_ascii=False)}"

if __name__ == '__main__':
    while True:
        user_input = input("Enter block number (or 'quit' to exit, 'history <name>' for account history): ")
        if user_input.lower() == 'quit':
            break

        if user_input.startswith("history "):
            parts = user_input.split()
            if len(parts) >= 2:
                account_name_to_fetch = parts[1]
                # Optional: allow specifying limit and start_from, e.g., "history username 50" or "history username 50 1000"
                history_limit = 10 # Default limit for CLI display
                start_op_index = -1 # Default to most recent

                if len(parts) > 2 and parts[2].isdigit():
                    history_limit = int(parts[2])
                    if not (0 < history_limit <= 1000):
                        print("History limit for display must be between 1 and 1000. Using default 10.")
                        history_limit = 10
                
                current_op_start_index = -1 # Initialize for pagination state
                total_ops_displayed_this_query = 0 # Initialize for new history query

                if len(parts) > 3 and parts[3].isdigit():
                    current_op_start_index = int(parts[3])
                    if current_op_start_index < 0: # -1 is valid.
                        print("Start operation index must be non-negative (or -1 for most recent). Using -1.")
                        current_op_start_index = -1
                
                # Inner loop for pagination
                while True:
                    # The 'start_from_op_index' for get_account_history is the actual Hive op sequence number.
                    # For the first call in a pagination sequence, if user specified a start, use that.
                    # If user didn't specify, current_op_start_index is -1 (most recent).
                    print(f"\nFetching history for {account_name_to_fetch} (limit {history_limit}, starting from op index {current_op_start_index})...")
                    history_data = get_account_history(account_name_to_fetch, limit=history_limit, start_from_op_index=current_op_start_index)

                    if not history_data: 
                        if history_data is None:
                            print("Failed to retrieve account history.")
                        else:
                            print("No more history found starting from this point.")
                        break 

                    current_batch_count = len(history_data)
                    start_display_index = total_ops_displayed_this_query + 1
                    end_display_index = total_ops_displayed_this_query + current_batch_count
                    
                    # Use actual op index from the data for more context if available
                    first_op_actual_index = history_data[0][0]
                    last_op_actual_index = history_data[-1][0]

                    print(f"\n--- Displaying operations {start_display_index}-{end_display_index} for {account_name_to_fetch} (Actual API op indexes: {first_op_actual_index} to {last_op_actual_index}) ---")
                    total_ops_displayed_this_query += current_batch_count
                    
                    for item_tuple in history_data:
                        if not (isinstance(item_tuple, list) and len(item_tuple) == 2):
                            print(f"  Malformed history item: {item_tuple}")
                            continue
                        
                        action_index = item_tuple[0]
                        tx_details = item_tuple[1]
                        
                        print(f"  Action Index: {action_index}")
                        print(f"    Timestamp: {tx_details.get('timestamp')}")
                        print(f"    Block: {tx_details.get('block')}")
                        print(f"    Transaction ID: {tx_details.get('trx_id', 'N/A')}")

                        op_field = tx_details.get('op')
                        op_type_str = "UnknownOperationType" # Default type
                        op_payload_dict = op_field # Default payload is the whole field

                        if isinstance(op_field, list) and len(op_field) == 2 and isinstance(op_field[0], str):
                            op_type_str = op_field[0]
                            op_payload_dict = op_field[1]
                        elif isinstance(op_field, dict) and 'type' in op_field and 'value' in op_field:
                            op_type_str = op_field['type']
                            op_payload_dict = op_field['value']
                        elif isinstance(op_field, dict): # If it's a dict but not the type/value structure
                            # Attempt to find a 'type' key, or default it.
                            # For payload, if 'value' exists use it, else the whole dict.
                            op_type_str = op_field.get('type', 'UnknownOperationTypeInDict')
                            op_payload_dict = op_field.get('value', op_field)
                        
                        print(f"    Operation Type: {op_type_str}")
                        # The instruction is to prepare for format_operation, 
                        # which will use op_type_str and op_payload_dict.
                        # The actual printing of details using format_operation is for the next step.
                        # For now, as a placeholder or if testing discretely, one might print op_payload_dict directly:
                        # print(f"    Raw Payload (for testing): {json.dumps(op_payload_dict, indent=2)}")
                        # But the final plan is to use:
                        print(f"    Details: {format_operation(op_type_str, op_payload_dict)}")

                    if len(history_data) < history_limit:
                        print("\nEnd of account history (fewer items returned than limit).")
                        break # Break from inner pagination loop
                    
                    last_op_sequence_index = history_data[-1][0]

                    if last_op_sequence_index == 0: # Reached the very first operation
                        print("\nReached the beginning of account history (operation index 0).")
                        break # Break from inner pagination loop

                    fetch_more = input("Fetch more history? (yes/no): ").lower()
                    if fetch_more == 'yes':
                        current_op_start_index = last_op_sequence_index -1
                        if current_op_start_index < 0: # Should not happen if last_op_sequence_index was not 0
                             print("\nReached the beginning of account history.")
                             break
                    else:
                        break # Break from inner pagination loop
            else:
                print("Invalid history command. Use: history <account_name> [limit] [start_op_index]")
        
        else: # Assume it's a block number
            try:
                block_num_to_fetch = int(user_input)
            except ValueError:
                print("Invalid input. Enter a block number, 'history <account_name>', or 'quit'.")
                continue

            block_data = get_block(block_num_to_fetch)

            if block_data:
                print(f"\n--- Block {block_num_to_fetch} Information ---")
                print(f"Timestamp: {block_data.get('timestamp')}")
                print(f"Witness: {block_data.get('witness')}")

                print("\n--- Transactions and Actions ---")
                transactions = block_data.get('transactions', [])
                if transactions:
                    for i, transaction in enumerate(transactions):
                        tx_id = block_data.get('transaction_ids', [])[i] if i < len(block_data.get('transaction_ids', [])) else "N/A"
                        print(f"  Transaction ID: {tx_id} (Block Num: {transaction.get('block_num')}, Tx in Block: {transaction.get('transaction_num')})")
                        
                        operations = transaction.get('operations', [])
                        if operations:
                            for operation_data_from_block in operations:
                                op_type_str = "UnknownOperationType"
                                op_payload_dict = operation_data_from_block # Default

                                if isinstance(operation_data_from_block, list) and len(operation_data_from_block) == 2 and isinstance(operation_data_from_block[0], str):
                                    op_type_str = operation_data_from_block[0]
                                    op_payload_dict = operation_data_from_block[1]
                                # Block operations are typically not in the {'type': ..., 'value': ...} format,
                                # but including for robustness or future API changes.
                                elif isinstance(operation_data_from_block, dict) and 'type' in operation_data_from_block and 'value' in operation_data_from_block:
                                    op_type_str = operation_data_from_block['type']
                                    op_payload_dict = operation_data_from_block['value']
                                elif isinstance(operation_data_from_block, dict) : 
                                     op_type_str = operation_data_from_block.get('type', 'UnknownOperationTypeInDict')
                                     op_payload_dict = operation_data_from_block.get('value', operation_data_from_block)
                                
                                print(f"    Operation Type: {op_type_str}")
                                print(f"    Details: {format_operation(op_type_str, op_payload_dict)}")
                        else:
                            print("    No operations in this transaction.")
                else:
                    print("  No transactions in this block.")
            else:
                print("Could not retrieve block data.")
        
        print() # Add a blank line for readability
