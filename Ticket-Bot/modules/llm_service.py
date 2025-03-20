
import os
import json
from langchain_pinecone import PineconeVectorStore
from langchain.chains import ConversationalRetrievalChain
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.embeddings.cohere import CohereEmbeddings

# Load API Keys
with open("api_keys.json", "r") as file:
    api_keys = json.load(file)

os.environ["COHERE_API_KEY"] = api_keys["COHERE_API_KEY"]
os.environ["PINECONE_API_KEY"] = api_keys["PINECONE_API_KEY"]
os.environ["GOOGLE_API_KEY"] = api_keys["GOOGLE_API_KEY"]

def initialize_retrieval_chain():
    try:
        llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            google_api_key=os.environ["GOOGLE_API_KEY"],
            temperature=0.3,
            max_tokens=1524,
            timeout=45,
            max_retries=3,
            user_agent="ticket"
        )

        embeddings = CohereEmbeddings(
            model="embed-english-v3.0", 
            cohere_api_key=os.environ["COHERE_API_KEY"],
            user_agent="ticket"
        )
        retriever = PineconeVectorStore.from_existing_index("ticket", embeddings).as_retriever(search_kwargs={"k": 5})

        return ConversationalRetrievalChain.from_llm(llm=llm, retriever=retriever, return_source_documents=False, verbose=True)

    except Exception as e:
        raise ValueError(f"Error during AI assistant initialization: {str(e)}")
