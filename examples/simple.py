import os
import sys
from browser_use import Agent, Browser, BrowserConfig
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

from browser_use import Agent
from pydantic import SecretStr

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

browser = Browser(
    config=BrowserConfig(
        browser_binary_path='/usr/bin/google-chrome',
    )
)

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))
llm1 = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))
task = 'Go to wikipedia.com, search for the deepseek.'


agent = Agent(task=task, llm=llm, planner_llm=llm1)

async def main():
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
