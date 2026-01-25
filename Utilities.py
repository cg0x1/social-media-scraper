from typing import List, final, Dict
from datetime import datetime, timezone
import hashlib
import base64
import sys
import re
import json
from urllib.parse import ParseResult, urlparse, parse_qs, urlunparse, urlencode

@final
class HashUtility():

    """
    Generates a SHA-1 hash of the input string and encodes it in a URL-safe Base64 format.
    """
    @staticmethod
    def generate_hash(input_string):

        if not input_string:
            raise ValueError("Input string cannot be null or empty.")

        encoding = 'mbcs' if sys.platform.startswith('win') else 'utf-8'

        input_bytes = input_string.encode(encoding)

        sha1_hash = hashlib.sha1(input_bytes).digest()

        base64_hash = base64.b64encode(sha1_hash).decode('ascii')

        safe_hash = base64_hash.replace('+', '-').replace('/', '_').replace('=', '')

        return safe_hash

@final
class UrlUtility():
    
    """
    Extracts the first query parameter value from a given URL.
    """
    @staticmethod
    def extract_origin_id(url):
        
        parsed_url = urlparse(url)
    
        query_params = parse_qs(parsed_url.query)

        if query_params:
            first_key = next(iter(query_params))
            # Return the first value associated with that key
            return query_params[first_key][0]
    
        return None
    
    @staticmethod
    def verify_url(url: str) -> tuple[bool, str]:

        parsed_url: ParseResult = urlparse(url)

        # Step 1: Parse query parameters
        query_params = parse_qs(parsed_url.query)
        
        if len(query_params) == 1 and 'v' in query_params:
            return True, url
        
        # Step 1: Remove 'pp' key if it exists
        query_params.pop('pp', None)

        # Step 3: Rebuild query string
        new_query = urlencode(query_params, doseq=True)

        # Step 4: Reconstruct full URL omitting any other querystring parameters
        new_url = urlunparse(parsed_url._replace(query=new_query))

        return False, new_url

@final
class DataTypeUtility():

    @staticmethod
    def try_parse_int(value: str) -> tuple[bool, int]:
        try:
            # Remove commas (as thousands separator)
            normalized_value = value.replace(",", "")
            result = int(normalized_value)
            return True, result
        except ValueError:
            return False, 0

@final
class UnknownAssetDateFormatEventArgs():
    def __init__(self, message, published, patterns):
        self.message = message
        self.published = published
        self.patterns = patterns

@final 
class DateUtility():
    
    @staticmethod
    def datetime_to_utc_string(input_datetime: datetime, enforce_utc: bool = True):
        try:
            if input_datetime is None or input_datetime == "0001-01-01T00:00:00":
                return datetime.min.strftime("%Y-%m-%dT%H:%M:%SZ")

            if not isinstance(input_datetime, datetime):
                raise TypeError("input_datetime must be a datetime object")

            if(enforce_utc):
                if input_datetime.tzinfo is None or input_datetime.tzinfo != timezone.utc:
                    raise ValueError("input_datetime must be timezone-aware and in UTC format")
            
            dt_string: str = input_datetime.strftime('%Y-%m-%dT%H:%M:%S.%f') + '0Z'

            return dt_string
        except TypeError as tx:
            raise ValueError(f"Invalid input type: {tx}") from tx
        except Exception as ex:
            raise ValueError(f"Error converting datetime to UTC string: {ex}") from ex

    @staticmethod
    def convert_literal_date(input_date_string) -> datetime:
        """
        Converts a date string from "%b %d, %Y" format to "YYYY-MM-DD" format.

        Args:
            input_date_string (str): The date string in "%b %d, %Y" format (e.g., "Nov 13, 2021").

        Returns:
            str: The date string in "YYYY-MM-DD" format (e.g., "2021-11-13"),
                 or None if parsing fails.
        """
        # Step 1: Parse the input string into a datetime object
        input_format = "%b %d, %Y"
        try:
            datetime_object = datetime.strptime(input_date_string, input_format)
            return datetime_object
        except ValueError as e:
            print(f"Error parsing input date string '{input_date_string}': {e}")
            return None

@final
class JsonConversionUtility:

    @staticmethod
    def to_json_pascal_case(entity):
        # Dynamically build PascalCase dictionary from instance __dict__
        data = {JsonConversionUtility.snake_to_pascal(k): v for k, v in entity.__dict__.items()}
        return json.dumps(data)
    
    @staticmethod
    def to_json(entity):
        json_string = json.loads(entity.__dict__.items())
        return json.dumps(json_string)
        # Dynamically build PascalCase dictionary from instance __dict__
        # data = {JsonConversionUtility.snake_to_pascal(k): v for k, v in entity.__dict__.items()}
        # return json.dumps(data)

    @staticmethod
    def to_json_dict(entity):
        # Useful for validation before dumping to JSON string
        return {JsonConversionUtility.snake_to_pascal(k): v for k, v in entity.__dict__.items()}
    
    @staticmethod
    def snake_to_pascal(s):
        return ''.join(word.capitalize() for word in s.split('_'))
