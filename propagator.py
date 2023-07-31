import json
import time
import asyncio
import websockets
import logging
import httpx
import secrets
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Any, Optional
from termcolor import colored

logger: logging.Logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

log_file: str = './logs/propagator.log'
handler: RotatingFileHandler = RotatingFileHandler(log_file, maxBytes=1000000, backupCount=5)
formatter: logging.Formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

class Event:
    def __init__(self, data):
        self.data = data

    async def extract_event_data(self):
        event_id = self.data.get("id")
        public_key = self.data.get("pubkey")
        kind_number = self.data.get("kind")
        created_at = self.data.get("created_at")
        tags = self.data.get("tags")
        content = self.data.get("content")
        signature_hex = self.data.get("sig")

        event_data = {
            "id": event_id,
            "pubkey": public_key,
            "kind": kind_number,
            "created_at": created_at,
            "tags": tags,
            "content": content,
            "sig": signature_hex,
        }

        return event_data
    

    async def fetch_online_relays(self) -> List[str]:
        url = "https://api.nostr.watch/v1/online"
        relay_list = []
    
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
    
            if response.status_code == 200:
                data = response.json()
    
                for relay in data:
                    relay_list.append(relay)
    
        return relay_list
    
    async def parse_returned_events(self, response: Dict, event_id: str) -> bool:
        response_event_id = response.get("id")
        #logger.debug(f"response_event_id = {response_event_id}")
        if event_id == response_event_id:
            logger.info(f"Response event id: {response_event_id} equals your event id: {event_id}")
            event_to_be_sent = response
                
        return event_to_be_sent

    async def query(self) -> List[str]:
        relays_to_send_event = []
    
        # Extracted event data
        event_data = await self.extract_event_data()
        event_id = event_data.get("id")
        public_key = event_data.get("pubkey")
        kind_number = event_data.get("kind")
        until_timestamp = int(event_data["created_at"]) + 10
    
        # Create the query dictionary
        query_dict = {
            "kinds": [kind_number],
            "limit": 3,
            "since": event_data["created_at"],
            "until": until_timestamp,
            "authors": [public_key]
        }
    
        online_relays = await self.fetch_online_relays()
        i = 1
        relays_note_exists = []
        for relay in online_relays:
            try:
                async with websockets.connect(relay) as ws:
                    logger.info(f"WebSocket connection created to {relay}")
    
                    subscription_id = secrets.token_hex(8)  # Generate a random 16-character string
                    q = query_dict
                    query_ws = json.dumps(("REQ", subscription_id, q))
    
                    await ws.send(query_ws)
                    logger.info(f"Query sent: {query_ws} to {relay}")
                    logger.info(f"This is relay #{i} of #{len(online_relays)} of online relays")
                    i += 1
    
                    response = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                    logger.debug(f"Response from {relay} is: {response}")
                    response_type = str(response[0])
    
                    if response_type == "EVENT":
                        
                        response_dict = response[2]
                        parsed_event = await self.parse_returned_events(response=response_dict, event_id=event_id )
                        #logger.debug(f"Parsed event variable is {response_dict} and {event_id}")                  
                        
                        logger.info(f"Event {event_id} was reported to be on {relay}!")
                        #logger.info(f"Sending event: {event_id}")
                        if parsed_event:
                            logger.debug(f"Not adding {relay} to list of realys to send")
                            relays_note_exists.append(relay)
                    else:  
                        logger.info(f"Event {event_id} does not exist on {relay}, an EOSE or other code was returned")
                        relays_to_send_event.append(relay) 
            except websockets.exceptions.WebSocketException as e:
                logger.error(f"WebSocket error occurred: {e}")
            except asyncio.TimeoutError:
                logger.warning(f"No response received from {relay} within 3 seconds. Moving to the next relay.")
            except Exception as ex:
                logger.error(f"Error occurred while communicating with {relay}: {ex}")
    
        return relays_to_send_event, relays_note_exists

    async def send_to_relays(self, relays_to_send, json_event_data) -> List[str]:
        i = 1
        relays_sent = []
        for relay in relays_to_send:
            async with websockets.connect(relay) as ws:
                logger.debug(f"This is realy # {i} of # {len(relays_to_send)}")
                i += 1
                try:
                    await ws.send(json.dumps(json_event_data))
                    logger.info(f"Sending EVENT: {json.dumps(json_event_data)} of type: {type(json.dumps(json_event_data))} ")
                    logger.info(f"Sent data to {relay} successfully")
                    relays_sent.append(relay)

                except websockets.exceptions.WebSocketException as e:
                    logger.error(f"WebSocket error occurred: {e}")
        return relays_sent
                
                    
def open_event_dictionary() -> Dict:
    try:
        with open("note_to_send", "r") as file:
            user_dict = json.load(file)
    except FileNotFoundError:
        print(colored("File 'note_to_send' not found.", "red"))
        return None
    except json.JSONDecodeError:
        print(colored("Invalid JSON format in the file 'note_to_send'.", "red"))
        return None

    return user_dict


user_dict = open_event_dictionary()
if user_dict is not None:
    logger.info(f"User provided event dictionary: {user_dict}")

async def main():
    start_time = time.time()
    data_extractor = Event(user_dict)
    user_supplied_event = await data_extractor.extract_event_data()
    query_time = await data_extractor.query()
    send_notes = await data_extractor.send_to_relays(relays_to_send=query_time[0], json_event_data=user_supplied_event)
    print("\nExtracted event data:", "green")
    print(colored(json.dumps(user_supplied_event, indent=2), "green"))

    logger.info(f"Your note was discovered on {len(query_time[1])} relays, specifically {query_time}")
    print(f"Your note was discovered on {len(query_time[1])} relays, specifically {query_time}")
 
    logger.info(f"Your notes was sent to {len(send_notes)} relays, specifically: {send_notes}")
    print(f"\n\nYou notes was sent to {len(send_notes)} relays, specifically: {send_notes}")

    end_time = time.time()
    elapsed_time = end_time - start_time
    elapsed_min = float(elapsed_time)/60
    logger.info(f"Elapsed time: {elapsed_time:.2f} seconds, or {elapsed_min} minutes")
    print(colored((f"Elapsed time: {elapsed_time:.2f} seconds, or {elapsed_min: .2f} minutes"), "red"))

asyncio.run(main())
