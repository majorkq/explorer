# This is the main script for Hive Explorer.
import json
import requests

HIVE_API_URL = "https://api.hive.blog"

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

if __name__ == '__main__':
    while True:
        user_input = input("Enter block number (or 'quit' to exit): ")
        if user_input.lower() == 'quit':
            break

        try:
            block_num_to_fetch = int(user_input)
        except ValueError:
            print("Invalid block number.")
            continue

        block_data = get_block(block_num_to_fetch)

        if block_data:
            print(f"\n--- Block {block_num_to_fetch} Information ---")
            print(f"Timestamp: {block_data.get('timestamp')}")
            print(f"Witness: {block_data.get('witness')}")

            print("\n--- Transactions and Actions ---")
            transactions = block_data.get('transactions', [])
            if transactions: # Check if transactions is not None and not empty
                for i, transaction in enumerate(transactions):
                    # Assuming transaction_ids are present at the block level
                    tx_id = block_data.get('transaction_ids', [])[i] if i < len(block_data.get('transaction_ids', [])) else "N/A"
                    # block_num and transaction_num are part of the transaction object itself in condenser_api.get_block response
                    print(f"  Transaction ID: {tx_id} (Block Num: {transaction.get('block_num')}, Tx in Block: {transaction.get('transaction_num')})")
                    
                    operations = transaction.get('operations', [])
                    if operations: # Check if operations is not None and not empty
                        for operation in operations:
                            if isinstance(operation, list) and len(operation) == 2:
                                op_type, op_payload = operation
                                print(f"    Operation Type: {op_type}")
                                print(f"    Details: {json.dumps(op_payload, indent=2)}") # Pretty print details
                            else:
                                print(f"    Unexpected operation format: {operation}")
                    else:
                        print("    No operations in this transaction.")
            else:
                print("  No transactions in this block.")
        else:
            # get_block already prints specific errors, so a generic message here is okay.
            # If get_block returns None because the block itself was empty (but valid), 
            # it might be desirable to distinguish that from an actual fetch error.
            # For now, "Could not retrieve block data" covers both.
            print("Could not retrieve block data.")
        
        print() # Add a blank line for readability
