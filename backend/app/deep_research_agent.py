from .models import embeddings, llm, llm_fast, llm_reasoning
from typing import TypedDict, Annotated, List, Literal
from playwright.async_api import Page, Locator
from operator import add
from pydantic import BaseModel, Field
from Browser.webrover_browser import WebRoverBrowser
from playwright.async_api import async_playwright
import asyncio
import platform
import urllib.parse
from pathlib import Path

def load_marking_script(filename: str) -> str:
    path = Path("marking_scripts") / filename
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "marking_scripts" / filename
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
from langchain_text_splitters import NLTKTextSplitter, SpacyTextSplitter, RecursiveCharacterTextSplitter
from newspaper import Article
import aiohttp
import asyncio
from io import BytesIO
from PyPDF2 import PdfReader
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import START, END, StateGraph
from IPython.display import Image, display



class Url(BaseModel):
    url: str | Literal["NO_CHANGE"] = Field(default="NO_CHANGE", description="The url to navigate to")

class SelfReview(BaseModel):
    answer: Literal["Yes", "No"]
    reasoning: str
    
class DomElement(TypedDict):
    index : int
    text : str
    type : str
    xpath : str
    x: float
    y: float
    description : str


class Action(TypedDict):
    thought : str
    action_type : Literal["click", "type", "scroll_read", "close_page", "wait", "go_back", "go_to_search", "retry", "respond"]
    args : str 
    action_element : DomElement



class SubtopicState(BaseModel):
    subtopics: List[str]

class SubtopicAnswer(BaseModel):
    subtopic: str
    subtopic_answer: str
    references: List[str] = Field(default_factory=list, description="List of all the references used in the subtopic answer")

class FinalAnswerComponents(BaseModel):
    introduction: str
    conclusion: str
    references: List[str] = Field(default_factory=list, description="List of all the references used in all the subtopic answers")

   

class AgentState(TypedDict):
    input: str
    page : Page
    dom_elements : List[DomElement]
    action : Action
    actions_taken : Annotated[List[str], add]
    visited_urls : Annotated[List[str], add]
    conversation_history: Annotated[List[str], add]
    new_page: Literal[True, False]
    subtopic_answers: Annotated[List[SubtopicAnswer], add]
    final_answer: str
    is_pdf: Literal[True, False]
    subtopics: List[str]
    subtopic_status: Annotated[List[str], add]
    subtopic_to_research: str
    number_of_urls_visited: int
    collect_more_info: Literal[True, False]
    
    


async def setup_browser(go_to_page: str):
    print(f"Setting up browser for {go_to_page}")
    browser = WebRoverBrowser()
    browser, context = await browser.connect_to_chrome()

    page = await context.new_page()
    
    try:
        await page.goto(go_to_page, timeout=80000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"Error loading page: {e}")
        # Fallback to Google if the original page fails to load/
        
        await page.goto("https://www.google.com", timeout=100000, wait_until="domcontentloaded")

    return browser, page


# Screen Annotations
from playwright.async_api import async_playwright
import asyncio

# Load the JavaScript file
marking_script = load_marking_script("final_marking.js")

async def execute_script(page):

    await asyncio.sleep(3)
    
    # Run the JavaScript marking function
    dom_tree = await page.evaluate(f"""
        (function() {{
            {marking_script}
            return captureInteractiveElements();
        }})();
    """)

        
    return dom_tree

async def remove_highlights(page):

    await asyncio.sleep(1)
    # Ensure the function is executed properly
    await page.evaluate("""
        (function() {
            if (typeof unmarkElements === 'function') {
                unmarkElements();
            } else {
                console.error('unmarkElements() not found. Re-injecting...');
                (function() {
                    function unmarkElements() {
                        console.log("Removing highlights...");

                        // Remove highlight container
                        const highlightContainer = document.getElementById('web-agent-highlight-container');
                        if (highlightContainer) {
                            highlightContainer.remove();
                            console.log("Highlight container removed.");
                        }

                        // Remove all highlight overlays
                        document.querySelectorAll("div").forEach(el => {
                            const style = window.getComputedStyle(el);
                            if (
                                (el.id && el.id.includes("highlight")) || 
                                style.border.includes("2px solid") || 
                                style.backgroundColor.includes("22") || 
                                style.zIndex === "2147483647"
                            ) {
                                el.remove();
                            }
                        });

                        // Remove lingering elements
                        setTimeout(() => {
                            document.querySelectorAll("[id^='highlight-'], div[style*='border: 2px solid'], div[style*='z-index: 2147483647']")
                                .forEach(el => el.remove());
                        }, 100);
                    }

                    unmarkElements();
                })();
            }
        })();
    """)



# Click

async def click(state: AgentState):
    page = state["page"]
    action_element = state["action"].get("action_element") or {}
    element_type = action_element.get("type", "")
    xpath = action_element.get("xpath")
    bbox_x = action_element.get("x")
    bbox_y = action_element.get("y")
    element_desc = action_element.get("description") or action_element.get("text") or "element"

    initial_page = page
    new_page_created = False
    clicked = False

    # Safely scroll element into view if possible without throwing
    if xpath:
        try:
            await page.locator(f'xpath={xpath}').scroll_into_view_if_needed(timeout=1500)
        except Exception:
            try:
                await page.evaluate(
                    """
                    (xpath) => {
                        try {
                            const result = document.evaluate(
                                xpath, 
                                document, 
                                null, 
                                XPathResult.FIRST_ORDERED_NODE_TYPE, 
                                null
                            );
                            const element = result.singleNodeValue;
                            if (element) {
                                element.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
                            }
                        } catch(e) {}
                    }
                    """,
                    xpath
                )
            except Exception:
                pass

    # 1. If it's a link, resolve its href and open in a new tab
    if element_type == "link" and xpath:
        try:
            loc = page.locator(f'xpath={xpath}')
            href = await loc.get_attribute("href", timeout=2000)
            if href:
                full_url = urllib.parse.urljoin(page.url, href)
                if full_url.startswith("http"):
                    try:
                        new_page = await page.context.new_page()
                        await new_page.goto(full_url, timeout=30000, wait_until="domcontentloaded")
                        state["page"] = new_page
                        new_page_created = True
                        clicked = True
                    except Exception as e:
                        print(f"Error opening new tab for {full_url}: {e}")
        except Exception:
            pass

    # 2. Try standard Playwright locator click
    if not clicked and xpath:
        try:
            loc = page.locator(f'xpath={xpath}')
            if element_type == "link":
                try:
                    async with page.context.expect_page(timeout=3000) as new_page_info:
                        if platform.system() == "Darwin":
                            await loc.click(modifiers=["Meta"], timeout=2500)
                        else:
                            await loc.click(modifiers=["Control"], timeout=2500)
                    new_page = await new_page_info.value
                    if new_page:
                        await new_page.bring_to_front()
                        await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                        state["page"] = new_page
                        new_page_created = True
                        clicked = True
                except Exception:
                    await loc.click(timeout=3000)
                    clicked = True
            else:
                await loc.click(timeout=3000)
                clicked = True
        except Exception:
            # Try force click with locator
            try:
                await page.locator(f'xpath={xpath}').click(force=True, timeout=2000)
                clicked = True
            except Exception:
                pass

    # 3. Fallback to coordinate-based clicking
    if not clicked and bbox_x is not None and bbox_y is not None and bbox_x > 0 and bbox_y > 0:
        try:
            await page.mouse.click(bbox_x, bbox_y)
            clicked = True
        except Exception as e:
            print(f"Coordinate click failed: {e}")

    await asyncio.sleep(2)

    if clicked:
        is_new = new_page_created or (state["page"] != initial_page)
        return {
            "actions_taken": [f"Clicked {element_type or 'element'} {element_desc}"],
            "page": state["page"],
            "new_page": is_new
        }
    else:
        try:
            await page.evaluate("window.scrollBy({ top: 300, behavior: 'smooth' });")
        except Exception:
            pass
        return {
            "actions_taken": [f"Attempted to click {element_desc}, continuing"],
            "page": state["page"],
            "new_page": False
        }


# After Click Router

async def after_click_router(state: AgentState):
    if state["new_page"]:
        return "scroll_and_read"
    else:
        return "annotate_page"
    

# Type

async def type(state: AgentState):
    """Types text into an input field located by its XPath, fallback bounding box if XPath fails."""
    page = state["page"]
    text = state["action"].get("args", "")
    action_element = state["action"].get("action_element") or {}
    element_description = f"{action_element.get('type', 'input')} element {action_element.get('description', '')}"

    typed = False
    bbox_x = action_element.get("x")
    bbox_y = action_element.get("y")
    xpath = action_element.get("xpath")

    if bbox_x is not None and bbox_y is not None and bbox_x > 0 and bbox_y > 0:
        try:
            await page.mouse.click(bbox_x, bbox_y, click_count=3)
            await asyncio.sleep(0.5)
            select_all = "Meta+A" if platform.system() == "Darwin" else "Control+A"
            await page.keyboard.press(select_all)
            await page.keyboard.press("Backspace")
            await page.keyboard.type(text)
            typed = True
        except Exception:
            pass

    if not typed and xpath:
        try:
            loc = page.locator(f'xpath={xpath}')
            await loc.click(timeout=2000)
            await loc.fill(text, timeout=2000)
            typed = True
        except Exception:
            pass

    # Press Enter to submit search/input
    await page.keyboard.press("Enter")
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=4000)
    except Exception:
        pass
    await asyncio.sleep(2)

    return {"actions_taken": [f"Typed '{text}' into {element_description} and submitted (pressed Enter). Search results should now be visible."]}


# Scroll Page 

async def scroll_page(state: AgentState):
    """Smoothly scrolls down until either the bottom of the page is reached or 10 scroll events have occurred, then scrolls back to the top."""
    page = state["page"]

    print(page.url)
    await page.evaluate("""
    async () => {
        const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
        let scrollCount = 0;
        
        // Scroll down until the bottom is reached or maximum 10 scrolls have been performed
        while (scrollCount < 10 && (window.innerHeight + window.scrollY) < document.body.scrollHeight) {
            window.scrollBy({ top: 650, left: 0, behavior: 'smooth' });
            scrollCount++;
            await delay(350);
        }
        
        // Scroll back to the top after scrolling down
        window.scrollTo({ top: 0, left: 0, behavior: 'smooth' });
        
        // Wait until the scroll position reaches the top
        while (window.scrollY > 0) {
            await delay(100);
        }
    }
    """)

    return {"actions_taken": [f"Scrolled down the page and collected information"]}


# Scroll pdf

async def scroll_pdf(state: AgentState):
    page = state["page"]
    # Click to ensure the PDF viewer is focused
    await page.mouse.click(300, 300)
    
    # Use smaller scroll increments for smoother scrolling.
    # For instance, scroll 100 pixels at a time, 50 times.
    for _ in range(50):
        await page.mouse.wheel(0, 300)
        await asyncio.sleep(0.1)

    for _ in range(10):
        await page.mouse.wheel(0, -1500)
        await asyncio.sleep(0.1)
    
    # Optionally, scroll back to the top.
    await page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
    return {"actions_taken": ["Scrolled PDF viewer and collected the relevant information"]}

# Close Page

async def close_page(state: AgentState):
    context = state["page"].context  # Get the browser context from the current page
    await state["page"].close()        # Close the current tab
    page = context.pages[-1] 
    print(page.url)
    return {"actions_taken": [f"Closed the current tab and switched to the last opened tab"], "page": page}


# Close Opened Link

async def close_opened_link(state: AgentState):
    current_url = state["page"].url
    context = state["page"].context  # Get the browser context from the current page
    await state["page"].close()        # Close the current tab
    page = context.pages[-1] 
    await page.evaluate("""
    async () => {
        const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
        // Scroll back to the top after scrolling down
        window.scrollTo({ top: 0, left: 0, behavior: 'smooth' });
                        
        // Wait until the scroll position reaches the top
        while (window.scrollY > 0) {
            await delay(100);
        }
    }
    """)
    print(page.url)
    return {"actions_taken": [f"Closed the opened link {current_url} and switched to {page.url}"], "page": page}


# Wait

async def wait(state: AgentState):
    """Waits for a specified amount of time."""
    seconds = state["action"]["args"]
    await asyncio.sleep(5)
    return {"actions_taken": [f"Waited for {seconds} seconds"]}


# Go Back 

async def go_back(state: AgentState):
    """Goes back to the previous page by calling window.history.back() and waiting for a known element."""
    page = state["page"]
    # Trigger back navigation via JavaScript.
    previous_page = page.url
    await page.evaluate("window.history.back()")
    # Wait a bit for the navigation to complete.
    # Optionally, you can wait for a specific selector you expect on the previous page:
    # await page.wait_for_selector("css=selector-of-known-element", timeout=30000)
    await page.wait_for_timeout(5000)
    current_page = page.url
    return {"actions_taken": [f"Navigated back to {current_page} from {previous_page}"]}



# Go to Search 

async def go_to_search(state: AgentState):
    """Goes to google.com"""
    page = state["page"]
    await page.goto("https://www.google.com", timeout=30000, wait_until="domcontentloaded")
    return {"actions_taken": [f"Navigated to Google"]}

# Scrape Text

async def scrape_text(page):        

# URL of the news article
    url = page.url

    # Create an Article object
    article = Article(url)

    # Download the article's HTML content
    try:
        article.download()

        # Parse the downloaded content
        article.parse()

        data = article.text

        if data == "":
            return "No data found"

        return data
   
    except Exception as e:
        return "Forbidden"

    
# Scrape PDF

async def scrape_pdf(page):
    """
    Fetches the PDF file from the current page's URL and extracts its text.
    Returns:
        - Extracted text if successful.
        - "No data found" if no text is extracted.
        - "Forbidden" if the PDF could not be downloaded.
    """
    url = page.url
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                content = await response.read()
                pdf_data = BytesIO(content)
                try:
                    reader = PdfReader(pdf_data)
                    text = ""
                    for page_num in range(len(reader.pages)):
                        page_obj = reader.pages[page_num]
                        page_text = page_obj.extract_text()
                        if page_text:
                            text += page_text + "\n"
                    if text.strip() == "":
                        return "No data found"
                    return text
                except Exception as e:
                    print(f"Error parsing PDF: {e}")
                    return "Forbidden"
            else:
                return "Forbidden"
            
# Docs from Text

async def docs_from_text(data, url):
    try:
        text_splitter = SpacyTextSplitter(chunk_size=500, chunk_overlap=10)
        texts = text_splitter.split_text(data)
    except Exception as e:
        print(f"SpacyTextSplitter failed ({e}), using RecursiveCharacterTextSplitter fallback")
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        texts = text_splitter.split_text(data)
    docs = [Document(page_content=text, metadata={"source": url}) for text in texts]
    return docs


async def store_doc_embeddings(docs):


    vector_store = Chroma(
        collection_name="webpage_rag",
        embedding_function=embeddings,
        persist_directory="./rag_store_webpage_gemini",
    )

    vector_store.add_documents(docs)



async def web_page_rag(state: AgentState):
    """Searches the web page for relevant information based on the User input"""
    page = state["page"]

    if state["is_pdf"]:
        result = await scrape_pdf(page)
    else:
        result = await scrape_text(page)

    if result == "Forbidden":
        return {"actions_taken": [f"Scraping the webpage {page.url} failed, should try another url"]}
    elif result == "No data found":
        return {"actions_taken": [f"No textual content found on the webpage {page.url}, try looking for url that has data"]}
    else:
        docs = await docs_from_text(result, page.url)
        print(len(docs))

        await store_doc_embeddings(docs)

        return {"actions_taken":[f"Scraped the url {page.url} and stored the information in a vector database for future reference"]}


async def note_scroll_read(state: AgentState):
    page = state["page"]
   
    url = str(page.url)

    visited_urls = state.get("visited_urls", [])

    if url in visited_urls:
        return state
    else:
        return {"visited_urls": [url]}


# URL Decide Node

async def url_decide_node(state: AgentState):
    input = state["input"]

    system_message = """
    You are an expert at deciding the url to navigate to.
    You will be given a task provided by the user and conversation history and the current page url.
    You will need to decide the url to navigate to.

    If the user's task is continuing from the previous conversation and same topic, return as NO_CHANGE.
    
    If user has a completely new task, decide the url to navigate to.
     - If its is something related information collection, navigate to google.
     - If its is something related to a specific website, navigate to the website.
     - For eg -
        1. If the user asks for the latest news on Apple's stock price, navigate to google.
        2. If user is asking to send an email to a specific person, navigate to gmail.
        3. If user is asking to book a flight, navigate to google to be able to search for flight booking sites later.
        4. If user is asking to find a restaurant, navigate to google maps.
        5. If the user is asking to book a hotel, navigate to google and search for hotel booking sites.

    Use this trick to decide the url to navigate to.
        - If the task is super specific to a website an can be performed only on that website, navigate to that website.
        - If the task is generic and can be performed on multiple websites, navigate to google to be able to search for more options later.

    Note: While returning the url, return the url in the format of the url and no text associated with it.
    """

    human_prompt = """
    This is the task provided by the user: {input}
    This is the conversation history: {conversation_history}
    This is the current page url: {page_url}
    """

    input = state["input"]
    conversation_history = state.get("conversation_history", [])
    page = state["page"]

    human_message = human_prompt.format(input=input, conversation_history=conversation_history, page_url=page.url)

    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=human_message)
    ]

    structured_llm = llm_fast.with_structured_output(Url)
    response = structured_llm.invoke(messages)
    print(response)

    page = state["page"]
    target_url = "NO_CHANGE"
    if response is not None:
        if hasattr(response, "url"):
            target_url = response.url
        elif isinstance(response, dict):
            target_url = response.get("url", "NO_CHANGE")

    if target_url and target_url != "NO_CHANGE" and isinstance(target_url, str) and target_url.startswith("http"):
        try:
            await page.goto(target_url)
        except Exception as e:
            print(f"Error navigating to {target_url}: {e}")

    return {"page": page}
    


async def topic_breakdown(state: AgentState):
    system_message = """ 
    You are an expert at breaking down a topic into smaller subtopics.
    You will be given a topic and you will need to break it down 3 smaller subtopics.

    Make sure teh subtopics are concise enough to be used as a search query.
    """

    human_prompt = """
    This is the topic: {topic}
    """

    input = state["input"]

    human_message = human_prompt.format(topic=input)

    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=human_message)
    ]

    response = llm.with_structured_output(SubtopicState).invoke(messages)

    subtopics = getattr(response, "subtopics", None) if response else None
    if not subtopics and isinstance(response, dict):
        subtopics = response.get("subtopics")
    if not subtopics:
        subtopics = [f"{input} background", f"{input} current state", f"{input} applications"]

    return {"subtopics": subtopics}


async def track_subtopic_status(state: AgentState):

    system_message = """ 
        You are an expert at tracking the status of research for a given list of subtopics.

        - You will be given a list of subtopics and their corresponding research statuses.
        - If the status is empty, it means no research has been done for any subtopic.
        - If some subtopics have been researched, determine the next subtopic that needs research.
        - If all subtopics have been researched, return "ALL_DONE".
        - Always prioritize selecting the first subtopic in the list that has not been researched yet.

        **Important Notes:**
        - Only return the **name** of the next subtopic that requires research.
        - Do not return "ALL_DONE" unless **all** subtopics have been researched.
        - Ensure logical prioritization: the next subtopic should be chosen based on list order.

        Example:
        - **Subtopics:** ["AI in Healthcare", "AI in Finance", "AI in Education"]
        - **Subtopic Status:** ["AI in Healthcare Completed", "", ""]
        - **Expected Output:** AI in Finance 
    """

    human_prompt = """
    This is the list of subtopics: {subtopics}
    This is the status of the research completed for each subtopic: {subtopic_status}
    """

    subtopics = state["subtopics"]
    subtopic_status = state.get("subtopic_status", [])

    human_message = human_prompt.format(subtopics=subtopics, subtopic_status=subtopic_status)

    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=human_message)
    ]

    response = llm_fast.invoke(messages)

    return {"subtopic_to_research": response.content}
    


async def research_router(state: AgentState):
    subtopic_to_research = state["subtopic_to_research"]

    if subtopic_to_research == "ALL_DONE":
        return "compile_research"
    else:
        return "go_to_search"
    

async def annotate_page(state: AgentState):
    page = state["page"]
    
    dom_elements = await execute_script(page)

    await remove_highlights(page)

    if dom_elements and dom_elements[0].get("type") == "pdf":
        return {"dom_elements": dom_elements, "is_pdf": True}
    else:
        return {"dom_elements": dom_elements, "is_pdf": False}




async def llm_call_node(state: AgentState):

    template = """ 
        You are WebRover, an autonomous AI agent designed to browse the web, interact with pages, and extract or aggregate information based on user queries—much like a human browsing the internet. You have access to the following tools:
            - Click Elements: Click on a specified element using its XPath. For links, open them in a new tab.
            - Type in Inputs: Type text into an input field identified by its XPath.
            - Scroll and Read (Scrape+RAG): Scroll down the page while scraping visible text and images to store in a vector database.
            - Close Page: Close the current tab and switch focus to the last opened tab.
            - Wait: Pause for a specified amount of time.
            - Go Back: Navigate back to the previous page.
            - Go to Search: Navigate to Google.

        Your inputs include:
            - The user's query (what the user wants to achieve).
            - A list of interactive DOM elements on the current page with properties: [xpath, type, text, description, x, y].
            - A record of actions taken so far.
            - A list of URLs already visited (do not revisit the same URL).

        Your task:
            - Decide the next best action (or a coherent sequence of actions) to move closer to fulfilling the user's request.
            - Evaluate the context by carefully reviewing the user's query, previous actions taken, visited URLs, and conversation history.
            - **Important:** When selecting a DOM element for an action, examine its "text" and "description" fields. For example, if the task is to input a departure date on Google Flights, only choose an input field if its description or visible text includes keywords like "departure", "depart", or "depart date". Do not select a generic input element that lacks specific contextual clues.
            - Avoid repeating the same search or action if it has already been performed without progress. If a search term or action was already attempted and yielded no new information, refine or change your approach.
            - Plan your steps: If multiple sequential actions are needed (e.g., scroll then click, or type a refined search query), output them in order until a page navigation or significant state change occurs.
            - Be natural and precise: Mimic human browsing behavior—click on visible links, type into search bars, scroll to reveal more content, and update your strategy if repeated results occur.

        Action guidelines:
            - Click Elements: Use for selecting links, buttons, or interactive items. If a link has already been followed (or if its URL is in the visited list), avoid re-clicking it.
            - Type in Inputs: Use for entering or refining search queries and form inputs. If the same query has been issued before, consider modifying or extending it.
            - Scroll and Read (Scrape+RAG): Use to gather content when no immediately actionable link is visible.
            - Close Page: Use when you need to exit a tab and return to a previous page.
            - Wait: Use to allow the page sufficient time to load or update after an action.
            - Go Back: Use when you need to return to a previous state or page.
            - Go to Search & WebPage Search: Use these to initiate or refine searches if no better actions are available.
            - Retry: Use only when you are unable to infer the next action from the current context.

        Output format:
            - Clearly output your action(s) in a structured format including:
                - Thought: Your reasoning behind the chosen action(s), considering previous attempts.
                - Action: The action to be taken.
                - Dom_element: (if applicable) the DOM element to interact with.
                - Reasoning: Detailed reasoning behind your action.
            - Do not output a repeated search term if it was already used and did not lead to progress; instead, suggest a refined or alternative approach.
            - Only output one coherent action or logical sequence of actions at a time, ensuring each step builds on previous actions logically and naturally.
        """



    prompt = ChatPromptTemplate(
    messages=[
        ("system", template),
        ("human", "Input: {input}"),
        ("human", "Actions Taken So far: {actions_taken}"),
        ("human", "Interactive Elements: {dom_elements}"),
        ("human", "Urls Already Visited: {visited_urls}"),
        
    ],
    input_variables=["input", "dom_elements", "actions_taken"],
    partial_variables={"actions_taken": [], "visited_urls": []},
    optional_variables=["actions_taken", "visited_urls"]
    )



    actions_taken = state.get("actions_taken", [])
    dom_elements = state["dom_elements"]
    input = state["subtopic_to_research"]
    visited_urls = state.get("visited_urls", [])
    prompt_value = prompt.invoke({"actions_taken": actions_taken, "dom_elements": dom_elements, "input": input, "visited_urls": visited_urls})

    response = llm.with_structured_output(Action).invoke(prompt_value)

    action = response

    return {"action": action}



tools = {
    "click" : "click",
    "type" : "type",
    "scroll_read" : "scroll_and_read",
    "close_page" : "close_page",
    "wait" : "wait",
    "go_back" : "go_back",
    "go_to_search" : "go_to_search",
}

def tool_router(state: AgentState):
    action = state["action"]
    action_type = action["action_type"]

    if action_type == 'retry':
        return "annotate_page"
    
    return tools[action_type]


async def scroll_and_read(state: AgentState):

    page = state["page"]
    await page.wait_for_load_state("domcontentloaded")
    
    page = state["page"]
    result = await page.evaluate("""
        () => {
            const url = window.location.href.toLowerCase();
            const isPDF = url.endsWith('.pdf') ||
                document.querySelector("embed[type*='pdf']") ||
                document.querySelector("iframe[src*='.pdf']");
                
            if (isPDF) {
                return "pdf";
            } else {
                return "webpage";
            }
        }
    """)
    return { "is_pdf": result == "pdf" }


async def webpage_or_pdf(state: AgentState):
    is_pdf = state["is_pdf"]

    if is_pdf:
        return "scroll_pdf"
    else:
        return "scroll_page"



async def self_review(state: AgentState):
    vector_store = Chroma(
    collection_name="webpage_rag",
    embedding_function=embeddings,
    persist_directory="./rag_store_webpage_gemini",
)

    input_text = state["subtopic_to_research"]
    relevant_docs = vector_store.similarity_search(input_text, k=40)

    print(f"Number of documents: {len(relevant_docs)}")

    system_message = """
    You are an expert at reviewing a set of relevant documents related to the user's query and deciding if the information is sufficient to answer the user's query.
    You will be given a user's query and a set of relevant documents.
    Answer only in the format of "Yes" or "No".

    Also state the reason for your answer.
    """

    human_prompt = """
    This is the user's query: {input}
    This is the set of documents: {relevant_docs}
    """

    human_message = human_prompt.format(input=input_text, relevant_docs=relevant_docs)

    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=human_message)
    ]

    structured_llm = llm.with_structured_output(SelfReview)
    response = structured_llm.invoke(messages)


    has_enough_info = False
    if response is not None:
        answer_val = getattr(response, "answer", None) if hasattr(response, "answer") else (response.get("answer") if isinstance(response, dict) else None)
        if answer_val == "Yes":
            has_enough_info = True
            reasoning_val = getattr(response, "reasoning", "") if hasattr(response, "reasoning") else (response.get("reasoning", "") if isinstance(response, dict) else "")
            state["actions_taken"] = reasoning_val

    if len(relevant_docs) > 30 or has_enough_info:
        return {"actions_taken" : [f"I have enough information on {input_text}. I will now proceed to write the article on {input_text}"], "collect_more_info" : False}
    else:
        return {"actions_taken" : [f"I need more information on {input_text}. I should visit more websites to gather  information on {input_text}"], "collect_more_info" : True}


async def after_self_router(state: AgentState):
    collect_more_info = state["collect_more_info"]
    if collect_more_info:
        return "annotate_page"
    else:
        return "subtopic_answer_node"


async def subtopic_answer_node(state: AgentState):

    vector_store = Chroma(
        collection_name="webpage_rag",
        embedding_function=embeddings,
        persist_directory="./rag_store_webpage_gemini",
    )

    input = state["subtopic_to_research"]

    relevant_docs = vector_store.similarity_search(input, k=40)
    

    system_message = """
        Role: Expert Article Writer for Research Compilation

        You are an expert in writing high-quality, well-structured, and thoroughly researched articles on assigned subtopics. Your article will be a 500-word standalone section that will later be compiled into a larger final article along with other subtopics.

        Your Task:
        Write a 500-word article on the given subtopic based on the provided documents.
        Ensure that the article is self-contained, insightful, and comprehensive, so it can be attached seamlessly to the final article.
        Use only the provided documents to support your writing and cite references properly.
        Guidelines for Writing the Article
        1. Provide a High-Quality and Insightful Article

        Comprehensive Coverage: Address all relevant aspects of the given subtopic.
        Accuracy: Ensure correctness by using only the provided documents as sources.
        Depth & Insight: Present nuanced explanations and well-supported arguments.
        2. Use Markdown Formatting for Clarity and Readability

        Headings and Subheadings: Organize your content logically.
        Bullet Points & Lists: Use lists where applicable to enhance readability.
        Emphasis: Use bold, italics, or code formatting to highlight key points.
        Code Blocks: Format code snippets correctly if needed.
        3. Cite Supporting Evidence with Proper APA-style Citations

        In-text Citations: Every fact, claim, or key idea taken from the provided documents must have an in-text citation in the format (Website Name, Date Accessed).
        Reference List: At the end of your article, include a "References" section listing all the sources you used, ensuring the numbering aligns with in-text citations.
        4. Ensure the Article is Well-Structured & Readable

        Logical Flow: Ensure the information transitions smoothly from one section to another.
        Concise & Clear Language: Avoid unnecessary complexity while maintaining depth.
        Self-Sufficiency: The article should be standalone and make sense even when read separately.
        
        Your article should be in the following format:

        Subtopic:
            [Subtopic Title]

        Subtopic Answer:

            # [Subtopic Title]

            (Introduction: A brief paragraph outlining the main points of the article.)

            1. Key Concept or Explanation

            Explanation supported by research (Website Name, Date Accessed).
            Additional supporting details or examples.
            
            2. Important Aspects or Steps

            Step 1 explanation (Website Name, Date Accessed).
            Step 2 explanation with supporting details.
            
            3. Applications, Challenges, or Future Implications

            Real-world application or significance of the subtopic.
            Any challenges or areas for further research (Website Name, Date Accessed).
            
            Key Takeaways:

            Summarize key takeaways from the article.
            Connect the discussion to the broader topic of the final article. 
            (Dont use the word conclusion, just summarize as key takeaways)


            (Do not include references in this section)
        
        References:
            [List of all the references used in the subtopic answer here]
            Website Name, Date Accessed.
            Website Name, Date Accessed.



        Key Notes:
        Stay within 500 words and ensure the article is self-contained while seamlessly integrating into a larger research piece.
        Do not add external information—use only the provided documents for accuracy.
        Ensure proper referencing so that citations align with the final compiled article.
    
    """

    human_prompt = """
    This is the user's query: {input}
    There are the relevant documents: {relevant_docs}
    """

    human_message = human_prompt.format(input=input, relevant_docs=relevant_docs)

    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=human_message)
    ]

    response = llm_reasoning.with_structured_output(SubtopicAnswer).invoke(messages)

    return {"subtopic_answers": [response], "subtopic_status": [f"Research on {input} completed"], "actions_taken": [f"Research on {input} completed"]}


async def empty_rag_store(state : AgentState):

    vector_store = Chroma(
    collection_name="webpage_rag",
    embedding_function=embeddings,
    persist_directory="./rag_store_webpage_gemini",
    )

    try:
        client = vector_store._client  # Access the underlying Chroma client
        client.delete_collection("webpage_rag")
        return {"actions_taken" : ["Emptied Vector Store"]}

    except Exception as e:
        print(f"Error deleting collection: {e}")
        return {"actions_taken" : ["Error Emptying Vector Store"]}

    
async def compile_research(state: AgentState):
    
    system_message = """
    You are an expert at compiling a set of subtopics to a broader research paper topic introduction,  conclusion and references section.
    Based on the subtopics and the broader research paper topic, write a nice introduction,  conclusion  and references section for the research paper.
    
    Use the list of visited urls to infer the links used in the references.
   
    You willbe give:
    - Broader Research Paper Topic
    - Subtopics
    - Subtopic Answers
    - List of visited urls

    Your output should be in the following format:
    # Introduction:
    [Introduction Content]

    # Conclusion:
    [Conclusion Content]

    # References:
    [References Content]
    
    """

    human_prompt = """
    This is the broader research paper topic: {broader_research_paper_topic}
    This is the set of subtopic and their answers: {subtopic_answers}
    This is the list of visited urls: {visited_urls}
    """

    broader_research_paper_topic = state["input"]
    subtopic_answers = state["subtopic_answers"]
    visited_urls = state["visited_urls"]

    human_message = human_prompt.format(broader_research_paper_topic=broader_research_paper_topic, subtopic_answers=subtopic_answers, visited_urls=visited_urls)

    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=human_message)
    ]

    response = llm_reasoning.with_structured_output(FinalAnswerComponents).invoke(messages)

    introduction = "# Introduction" + "\n" + response.introduction 

    subtopic_answers = "\n".join([subtopic_answer.subtopic_answer for subtopic_answer in subtopic_answers])

    conclusion = "# Conclusion" + "\n" + response.conclusion
    
    references_list = response.references

    references = "# References" + "\n" + "\n".join(["\n - " + reference for reference in references_list])

    final_answer = introduction + "\n" + subtopic_answers + "\n" + conclusion + "\n" + references

    

    return {"final_answer": final_answer, "actions_taken": [f"Research Paper on {broader_research_paper_topic} completed"], "conversation_history": [f"User : {state['input']}"]+[f"WebRover : {final_answer}"]}
    
    


builder = StateGraph(AgentState)

builder.add_node("url_decide_node", url_decide_node)
builder.add_node("topic_breakdown", topic_breakdown)
builder.add_node("track_subtopic_status", track_subtopic_status)
builder.add_node("annotate_page", annotate_page)
builder.add_node("llm_call_node", llm_call_node)
builder.add_node("click", click)
builder.add_node("type", type)
builder.add_node("scroll_page", scroll_page)
builder.add_node("scroll_pdf", scroll_pdf)
builder.add_node("scroll_and_read", scroll_and_read)
builder.add_node("web_page_rag", web_page_rag)
builder.add_node("note_scroll_read", note_scroll_read)
builder.add_node("close_page", close_page)
builder.add_node("wait", wait)
builder.add_node("go_back", go_back)
builder.add_node("go_to_search", go_to_search)
builder.add_node("subtopic_answer_node", subtopic_answer_node)
builder.add_node("empty_rag_store", empty_rag_store)
builder.add_node("close_opened_link", close_opened_link)
builder.add_node("self_review", self_review)
builder.add_node("compile_research", compile_research)


builder.add_edge(START, "url_decide_node")
builder.add_edge("url_decide_node", "topic_breakdown")
builder.add_edge("topic_breakdown", "track_subtopic_status")
builder.add_conditional_edges("track_subtopic_status", research_router, ["go_to_search", "compile_research"])
builder.add_edge("annotate_page", "llm_call_node")
builder.add_conditional_edges("llm_call_node", tool_router, ["annotate_page", "click", "type", "scroll_and_read", "close_page", "wait", "go_back", "go_to_search"])
builder.add_edge("scroll_and_read", "web_page_rag")
builder.add_conditional_edges("scroll_and_read", webpage_or_pdf, ["scroll_page", "scroll_pdf"])
builder.add_edge("scroll_pdf", "note_scroll_read")
builder.add_edge("scroll_page", "note_scroll_read")
builder.add_edge("web_page_rag", "note_scroll_read")
builder.add_edge("note_scroll_read", "close_opened_link")
builder.add_edge("close_opened_link", "self_review")
builder.add_conditional_edges("self_review", after_self_router, ["annotate_page", "subtopic_answer_node"])
builder.add_edge("subtopic_answer_node", "empty_rag_store")
builder.add_edge("empty_rag_store", "track_subtopic_status")
builder.add_edge("compile_research", END)
builder.add_conditional_edges("click", after_click_router, ["annotate_page", "scroll_and_read"])
builder.add_edge("type", "annotate_page")
builder.add_edge("close_page", "annotate_page")
builder.add_edge("wait", "annotate_page")
builder.add_edge("go_back", "annotate_page")
builder.add_edge("go_to_search", "annotate_page")

deep_research_agent = builder.compile()
