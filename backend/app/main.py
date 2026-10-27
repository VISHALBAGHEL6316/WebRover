from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
from typing import Optional, Dict, Any, Literal
from contextlib import asynccontextmanager
import json
import time
# Import necessary functions from agent files
from .task_agent import task_agent
from .research_agent import research_agent, type
from .deep_research_agent import deep_research_agent
from .browser_manager import setup_browser, cleanup_browser_session

from fastapi.middleware.cors import CORSMiddleware

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Your Next.js app URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables for browser session
browser_session = {
    "browser": None,
    "page": None
}

# Global event for stopping current model execution
stop_event = asyncio.Event()

# Global queue for browser events
browser_events = asyncio.Queue()

class BrowserSetupRequest(BaseModel):
    url: str = "https://www.google.com"

class QueryRequest(BaseModel):
    query: str
    agent_type: Literal["task", "research", "deep_research"]

@app.post("/setup-browser")
async def setup_browser_endpoint(request: BrowserSetupRequest):
    try:
        # Clear any existing session
        if browser_session["browser"]:
            await cleanup_browser()
            
        # Setup new browser session
        if request.url == "https://www.google.com":
            print(f"Setting up browser for {request.url}")
            browser, page = await setup_browser(request.url)
        else:
            browser, page = await setup_browser(request.url)
        
        # Store session info
        browser_session.update({
            "browser": browser,
            "page": page
        })
        
        return {"status": "success", "message": "Browser setup complete"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to setup browser: {str(e)}")

@app.post("/cleanup")
async def cleanup_browser():
    try:
        if browser_session["browser"]:
            # Use the proper cleanup function
            await cleanup_browser_session(browser_session["browser"])
            
            # Clear the session
            browser_session.update({
                "browser": None,
                "page": None
            })
        
        return {"status": "success", "message": "Browser cleanup complete"}
    except Exception as e:
        print(f"Cleanup error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup browser: {str(e)}")

@app.post("/stop")
async def stop_execution():
    print("Stop requested by user, signalling stop_event...")
    stop_event.set()
    return {"status": "success", "message": "Model execution stopped"}

async def emit_browser_event(event_type: str, data: Dict[str, Any]):
    await browser_events.put({
        "type": event_type,
        "data": data
    })

@app.get("/browser-events")
async def browser_events_endpoint():
    async def event_generator():
        while True:
            try:
                event = await browser_events.get()
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.CancelledError:
                break
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

def sse_event(event_type: str, content: Any = None, **kwargs) -> str:
    payload: Dict[str, Any] = {"type": event_type}
    if content is not None:
        payload["content"] = content
    payload.update(kwargs)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

def get_field(obj: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(field_name, default)
    return getattr(obj, field_name, default)

async def stream_task_agent_response(query: str, page, agent_graph):
    try:
        initial_state = {
            "input": query,
            "page": page,
            "master_plan": None,
            "dom_elements": [],
            "chat_history": [],
            "decide_action": None,
            "actions_taken": [],
            "actions": None,
            "response": ""
        }
        
        async for event in agent_graph.astream(
            initial_state,
            {"recursion_limit": 400}
        ):
            if stop_event.is_set():
                print("Stop requested, terminating task agent...")
                yield sse_event("thought", "Model execution stopped by user.")
                yield sse_event("final_response", "Model execution stopped by user.")
                break
            try:
                yield sse_event("keepalive", timestamp=time.time())
                await asyncio.sleep(0.1)
                
                if isinstance(event, dict):
                    if "decide_immediate_action" in event:
                        decide_action = event["decide_immediate_action"].get("decide_action")
                        thought = get_field(decide_action, "thought")
                        if thought:
                            yield sse_event("thought", thought)
                    
                    if "decide_url" in event:
                        action = event["decide_url"].get("actions_taken")
                        yield sse_event("action", action)
                    
                    dom_keys = ["get_all_elements", "get_all_input_elements", "get_all_button_elements", "get_all_link_elements"]
                    matching_dom_key = next((k for k in dom_keys if k in event), None)
                    if matching_dom_key:
                        action = event[matching_dom_key].get("actions_taken")
                        yield sse_event("dom_update", action)
                    
                    interact_keys = ["interact_with_input_elements", "interact_with_button_elements", "interact_with_link_elements"]
                    matching_interact_key = next((k for k in interact_keys if k in event), None)
                    if matching_interact_key:
                        actions_obj = event[matching_interact_key].get("actions")
                        actions = get_field(actions_obj, "element_actions")
                        yield sse_event("interaction", actions)
                    
                    action_keys = ["click", "type", "wait", "go_back", "go_to_search"]
                    matching_action_key = next((k for k in action_keys if k in event), None)
                    if matching_action_key:
                        actions = event[matching_action_key].get("actions_taken")
                        yield sse_event("browser_action", actions)
                    
                    if "respond" in event:
                        response = event["respond"].get("response")
                        yield sse_event("final_response", response)
                        
                    yield sse_event("keepalive", timestamp=time.time())
                        
            except Exception as e:
                yield sse_event("error", str(e))
                continue
                
    except Exception as e:
        yield sse_event("error", str(e))
    finally:
        await asyncio.sleep(0.5)
        yield sse_event("keepalive", timestamp=time.time())
        yield sse_event("complete", "Processing completed")
        await asyncio.sleep(0.5)
        yield sse_event("end", "Stream completed")

async def stream_research_agent_response(query: str, page, agent_graph):
    try:
        initial_state = {
            "input": query,
            "page": page,
            "dom_elements": [],
            "action": None,
            "actions_taken": [],
            "visited_urls": [],
            "conversation_history": [],
            "answer": "",
            "new_page": False,
            "is_pdf": False
        }
        
        async for event in agent_graph.astream(
            initial_state,
            {"recursion_limit": 400}
        ):
            if stop_event.is_set():
                print("Stop requested, terminating task agent...")
                yield sse_event("thought", "Model execution stopped by user.")
                yield sse_event("final_response", "Model execution stopped by user.")
                break
            try:
                yield sse_event("keepalive", timestamp=time.time())
                
                if isinstance(event, dict):
                    if "llm_call_node" in event:
                        action_data = event["llm_call_node"].get("action")
                        thought = get_field(action_data, "thought")
                        if thought:
                            yield sse_event("thought", thought)
                    
                    action_keys = ["click", "type", "wait", "go_back", "go_to_search"]
                    matching_action_key = next((k for k in action_keys if k in event), None)
                    if matching_action_key:
                        actions = event[matching_action_key].get("actions_taken")
                        yield sse_event("action", actions)
                    
                    if "web_page_rag" in event:
                        action = event["web_page_rag"].get("actions_taken")
                        yield sse_event("rag_action", action)
                    
                    if "self_review" in event:
                        action = event["self_review"].get("actions_taken")
                        yield sse_event("review", action)
                    
                    if "close_opened_link" in event:
                        action = event["close_opened_link"].get("actions_taken")
                        yield sse_event("close_tab", action)
                    
                    if "answer_node" in event:
                        action = event["answer_node"].get("actions_taken")
                        yield sse_event("action", action)
                        
                        answer = event["answer_node"].get("answer")
                        yield sse_event("final_answer", answer)
                        
                        conversation_history = event["answer_node"].get("conversation_history")
                        yield sse_event("conversation_history", conversation_history)
                    
                    if "empty_rag_store" in event:
                        action = event["empty_rag_store"].get("actions_taken")
                        yield sse_event("cleanup", action)
                        
                await asyncio.sleep(0.1)
                        
            except Exception as e:
                yield sse_event("error", str(e))
                continue
                
    except Exception as e:
        yield sse_event("error", str(e))
    finally:
        await asyncio.sleep(0.5)
        yield sse_event("complete", "Processing completed")
        await asyncio.sleep(0.5)
        yield sse_event("end", "Stream completed")

async def stream_deep_research_agent_response(query: str, page, agent_graph):
    try:
        initial_state = {
            "input": query,
            "page": page,
            "dom_elements": [],
            "action": None,
            "actions_taken": [],
            "visited_urls": [],
            "conversation_history": [],
            "subtopics": [],
            "subtopic_answers": [],
            "final_answer": "",
            "new_page": False,
            "is_pdf": False,
            "subtopic_status": [],
            "subtopic_to_research": "",
            "number_of_urls_visited": 0,
            "collect_more_info": False
        }
        
        async for event in agent_graph.astream(
            initial_state,
            {"recursion_limit": 400}
        ):
            if stop_event.is_set():
                print("Stop requested, terminating task agent...")
                yield sse_event("thought", "Model execution stopped by user.")
                yield sse_event("final_response", "Model execution stopped by user.")
                break
            try:
                yield sse_event("keepalive", timestamp=time.time())
                
                if isinstance(event, dict):
                    if "topic_breakdown" in event:
                        subtopics = event["topic_breakdown"].get("subtopics", [])
                        yield sse_event("subtopics", subtopics)
                    
                    if "llm_call_node" in event:
                        action_data = event["llm_call_node"].get("action")
                        thought = get_field(action_data, "thought")
                        if thought:
                            yield sse_event("thought", thought)
                    
                    action_keys = ["click", "type", "wait", "go_back", "go_to_search"]
                    matching_action_key = next((k for k in action_keys if k in event), None)
                    if matching_action_key:
                        action = event[matching_action_key].get("actions_taken")
                        yield sse_event("browser_action", action)
                    
                    if "web_page_rag" in event:
                        action = event["web_page_rag"].get("actions_taken")
                        yield sse_event("rag_action", action)
                    
                    if "self_review" in event:
                        action = event["self_review"].get("actions_taken")
                        yield sse_event("review", action)
                    
                    if "subtopic_answer_node" in event:
                        action = event["subtopic_answer_node"].get("actions_taken")
                        yield sse_event("subtopic_answer", action)
                        
                        subtopic_status = event["subtopic_answer_node"].get("subtopic_status")
                        yield sse_event("subtopic_status", subtopic_status)
                    
                    if "close_opened_link" in event:
                        action = event["close_opened_link"].get("actions_taken")
                        yield sse_event("close_tab", action)
                    
                    if "compile_research" in event:
                        action = event["compile_research"].get("actions_taken")
                        yield sse_event("compile", action)
                        
                        answer = event["compile_research"].get("final_answer")
                        yield sse_event("final_answer", answer)
                        
                        conversation_history = event["compile_research"].get("conversation_history")
                        yield sse_event("conversation_history", conversation_history)
                    
                    if "empty_rag_store" in event:
                        action = event["empty_rag_store"].get("actions_taken")
                        yield sse_event("cleanup", action)
                        
                await asyncio.sleep(0.1)
                        
            except Exception as e:
                yield sse_event("error", str(e))
                continue
                
    except Exception as e:
        yield sse_event("error", str(e))
    finally:
        await asyncio.sleep(0.5)
        yield sse_event("complete", "Processing completed")
        await asyncio.sleep(0.5)
        yield sse_event("end", "Stream completed")

@app.post("/query")
async def query_agent(request: QueryRequest):
    stop_event.clear()
    page = browser_session.get("page")
    if not page or page.is_closed():
        try:
            print("Browser not initialized or closed, auto-setting up browser...")
            browser, page = await setup_browser("https://www.google.com")
            browser_session.update({
                "browser": browser,
                "page": page
            })
        except Exception as e:
            raise HTTPException(
                status_code=400, 
                detail=f"Browser not initialized and auto-setup failed: {str(e)}"
            )
    
    agent_graphs = {
        "task": task_agent,
        "research": research_agent,
        "deep_research": deep_research_agent
    }
    
    stream_handlers = {
        "task": stream_task_agent_response,
        "research": stream_research_agent_response,
        "deep_research": stream_deep_research_agent_response
    }
    
    return StreamingResponse(
        stream_handlers[request.agent_type](
            request.query, 
            browser_session["page"],
            agent_graphs[request.agent_type]
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked"
        }
    )


@app.post("/api/docs/type")
async def type_in_docs(request: Request):
    try:
        if not browser_session["page"]:
            return JSONResponse(
                status_code=400,
                content={"error": "Browser not initialized. Call /setup-browser first"}
            )

        data = await request.json()
        content = data.get('content')
        
        if not content:
            return JSONResponse(
                status_code=400,
                content={"error": "Content is required"}
            )

        page = browser_session["page"]
        await page.goto('https://docs.google.com/document/create')
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(2)  # Wait for editor to be fully loaded

        # Wait for and click the editor canvas
        editor_selector = ".kix-appview-editor"
        await page.wait_for_selector(editor_selector)
        editor = await page.query_selector(editor_selector)
        
        if editor:
            bbox = await editor.bounding_box()
            if bbox:
                # Click in the middle of the editor
                x = bbox['x'] + bbox['width'] / 2
                y = bbox['y'] + bbox['height'] / 2
                
                await page.mouse.click(x, y)
                await asyncio.sleep(1)

                state = {
                    "page": page,
                    "action": {
                        "action_element": {
                            "type": "text_editor",
                            "description": "Google Docs editor",
                            "x": x,
                            "y": y,
                            "xpath": f"//div[contains(@class, 'kix-appview-editor')]",
                            "inViewport": True
                        },
                        "args": content
                    }
                }
                
                result = await type(state)
                
                return JSONResponse(
                    status_code=200,
                    content={"message": "Content typed successfully", "actions": result["actions_taken"]}
                )
        
        return JSONResponse(
            status_code=500,
            content={"error": "Text editor not found"}
        )
            
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to type content: {str(e)}"}
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
