from dotenv import load_dotenv
import os

load_dotenv()

# Test Groq
from langchain_groq import ChatGroq
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)
response = llm.invoke("Say 'setup works' and nothing else.")
print("Groq:", response.content)

# Test Tavily
from tavily import TavilyClient
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
results = tavily.search("LangGraph multi-agent systems", max_results=1)
print("Tavily:", results['results'][0]['title'])

print("\n✅ All good. Ready to build.")