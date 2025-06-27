from abc import ABC, abstractmethod
from models import AIProvider
from typing import Dict, Any
import json
from models import AIProvider  # Now this will work


class OpenAIGPTProvider(AIProvider):
    def __init__(self):
        from openai import OpenAI
        self.client = None
        self.OpenAI = OpenAI
    
    def initialize(self, api_key: str):
        self.client = self.OpenAI(api_key=api_key)
    
    def generate_response(self, system_prompt: str, user_message: str) -> str:
        models_to_try = ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]
        last_error = None
        
        for model in models_to_try:
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    max_tokens=400,
                    temperature=0.3
                )
                return response.choices[0].message.content
            except Exception as e:
                last_error = e
                continue
        
        raise last_error or Exception("No models available")

class GeminiProvider(AIProvider):
    def __init__(self):
        import google.generativeai as genai
        self.genai = genai
        self.model = None
    
    def initialize(self, api_key: str):
        self.genai.configure(api_key=api_key)
        try:
            self.model = self.genai.GenerativeModel('gemini-1.5-flash')
        except:
            self.model = self.genai.GenerativeModel('gemini-1.5-pro')
    
    def generate_response(self, system_prompt: str, user_message: str) -> str:
        full_prompt = f"{system_prompt}\n\nUser Message: {user_message}"
        try:
            response = self.model.generate_content(
                full_prompt,
                generation_config={
                    "temperature": 0.3,
                    "max_output_tokens": 400
                }
            )
            return response.text
        except Exception as e:
            print(f"Gemini API Error: {str(e)}")
            return "Sorry, I'm having trouble generating a response. Please try again."

class AIProviderFactory:
    @staticmethod
    def create_provider(provider_name: str):
        providers = {
            "openai": OpenAIGPTProvider,
            "gemini": GeminiProvider
        }
        
        if provider_name.lower() not in providers:
            raise ValueError(f"Unsupported provider: {provider_name}")
        
        return providers[provider_name.lower()]()