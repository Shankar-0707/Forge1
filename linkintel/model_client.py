import urllib.request
import urllib.error
import json
import os
import time
import re

class OllamaClient:
    def __init__(self, model: str = None):
        self.model = model or os.environ.get("LI_MODEL") or os.environ.get("RADAR_MODEL") or "gpt-oss:20b-cloud"
        self.call_count = 0
        self.base_url = "http://localhost:11434"
        self._available_cache = None
        self._available_cache_time = 0

    def is_available(self) -> bool:
        now = time.time()
        if self._available_cache is not None and (now - self._available_cache_time < 60):
            return self._available_cache

        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    self._available_cache = True
                else:
                    self._available_cache = False
        except Exception:
            self._available_cache = False
            
        self._available_cache_time = now
        return self._available_cache

    def generate(self, prompt: str, system: str = None, max_tokens: int = 1024, temperature: float = 0.3) -> str:
        self.call_count += 1
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature
            }
        }
        if system:
            payload["system"] = system

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get("response", "")
        except Exception as e:
            print(f"[Warning] Ollama model call failed: {e}")
            return ""

    def extract_json(self, text: str):
        if not text:
            return None
        
        # Try to parse raw text first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
            
        # Try to find markdown code fences
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
                
        # Try to find anything looking like a JSON object or array
        match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
                
        return None

_client = None

def get_client() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client

def model_available() -> bool:
    return get_client().is_available()

def model_generate(prompt: str, system: str = None) -> str:
    return get_client().generate(prompt, system=system)

def model_call_count() -> int:
    return get_client().call_count

def model_name() -> str:
    return get_client().model

if __name__ == "__main__":
    print(f"Testing model client...")
    print(f"Model configured: {model_name()}")
    
    if model_available():
        print("Model is AVAILABLE. Sending test prompt...")
        response = model_generate("Name 3 fruits in JSON array format.")
        print(f"Raw response:\n{response}\n")
        
        parsed = get_client().extract_json(response)
        if parsed:
            print(f"Successfully parsed JSON: {parsed}")
        else:
            print("Failed to parse JSON from response.")
    else:
        print("Model is UNAVAILABLE. Please start Ollama.")
