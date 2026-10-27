'use client';

import { useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { ResponseDisplay } from '@/components/rover/ResponseDisplay';
import { QueryInput } from '@/components/rover/QueryInput';
import { ParticlesBackground } from '@/components/ui/ParticlesBackground';
import { ToggleSwitch } from '@/components/ui/ToggleSwitch';

interface Message {
  type: 'thought' | 'action' | 'dom_update' | 'interaction' | 'browser_action' | 
        'rag_action' | 'review' | 'close_tab' | 'subtopics' | 'subtopic_answer' |
        'subtopic_status' | 'compile' | 'final_answer' | 'conversation_history' |
        'cleanup' | 'error' | 'final_response' | 'user_input';
  content: string;
}

type AgentType = 'task' | 'research' | 'deep_research';

export default function RoverPage() {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isResearchMode, setIsResearchMode] = useState(true);
  const [isDeepResearch, setIsDeepResearch] = useState(true);

  const currentAgent: AgentType = isResearchMode 
    ? (isDeepResearch ? 'deep_research' : 'research')
    : 'task';

  const abortControllerRef = useRef<AbortController | null>(null);

  const handleStop = async () => {
    try {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      await fetch('http://localhost:8000/stop', {
        method: 'POST',
      });
      setIsLoading(false);
      setMessages(prev => [...prev, {
        type: 'thought',
        content: 'Model execution stopped by user.'
      }]);
    } catch (err) {
      console.error('Failed to stop query:', err);
      setIsLoading(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      const response = await fetch('http://localhost:8000/cleanup', {
        method: 'POST',
      });
      
      if (!response.ok) {
        throw new Error('Failed to cleanup browser');
      }
      
      await router.push('/');
    } catch (error) {
      console.error('Failed to cleanup browser:', error);
      // Still try to navigate even if cleanup fails
      await router.push('/');
    }
  };

  const handleStreamingResponse = async (response: Response) => {
    const reader = response.body?.getReader();
    if (!reader) throw new Error('No response reader');

    const decoder = new TextDecoder();
    let buffer = '';

    const processSSEMessage = (jsonStr: string) => {
      try {
        const data = JSON.parse(jsonStr);
        
        if (data.type === 'keepalive' || data.type === 'complete' || data.type === 'end') return;
        
        // Clean content if it matches the pattern
        const cleanContent = (content: unknown): string => {
          if (content === null || content === undefined) return '';
          // If content is already an array, join into string
          if (Array.isArray(content)) {
            return content.map(item => typeof item === 'object' ? JSON.stringify(item) : String(item)).join('\n');
          }
          
          if (typeof content === 'string') {
            try {
              // Try to parse as JSON
              const parsed = JSON.parse(content);
              if (Array.isArray(parsed)) {
                return parsed.map(item => typeof item === 'object' ? JSON.stringify(item) : String(item)).join('\n');
              }
              // If it's a string with ["..."] pattern
              if (content.startsWith('["') && content.endsWith('"]')) {
                return content.slice(2, -2);
              }
            } catch {
              // If parsing fails and it has the pattern
              if (content.startsWith('["') && content.endsWith('"]')) {
                return content.slice(2, -2);
              }
            }
            return content;
          }
          return typeof content === 'object' ? JSON.stringify(content) : String(content);
        };

        const processedData: Message = {
          type: data.type,
          content: cleanContent(data.content)
        };
        
        // Handle different message types based on agent
        switch (data.type) {
          case 'thought':
          case 'action':
          case 'browser_action':
          case 'final_answer':
          case 'final_response':
          case 'dom_update':
          case 'interaction':
          case 'error':
          case 'rag_action':
          case 'review':
          case 'close_tab':
          case 'cleanup':
          case 'subtopics':
          case 'subtopic_answer':
          case 'subtopic_status':
          case 'compile':
            setMessages(prev => [...prev, processedData]);
            break;
        }
      } catch (e) {
        console.error('Failed to parse SSE message:', jsonStr, e);
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      
      const parts = buffer.split(/\r?\n\r?\n/);
      buffer = parts.pop() || '';
      
      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;
        
        let jsonStr = '';
        if (trimmed.startsWith('data:')) {
          const lines = trimmed.split(/\r?\n/);
          jsonStr = lines.map(line => line.replace(/^data:\s*/, '')).join('\n').trim();
        } else {
          jsonStr = trimmed;
        }
        
        if (jsonStr) {
          processSSEMessage(jsonStr);
        }
      }
    }

    if (buffer.trim()) {
      const trimmed = buffer.trim();
      let jsonStr = '';
      if (trimmed.startsWith('data:')) {
        const lines = trimmed.split(/\r?\n/);
        jsonStr = lines.map(line => line.replace(/^data:\s*/, '')).join('\n').trim();
      } else {
        jsonStr = trimmed;
      }
      if (jsonStr) {
        processSSEMessage(jsonStr);
      }
    }
  };

  const handleSubmit = async (e?: React.FormEvent<HTMLFormElement>) => {
    if (e) {
      e.preventDefault();
    }
    if (!query.trim() || isLoading) return;

    setIsLoading(true);
    // Add user message to the chat history
    setMessages(prev => [...prev, { type: 'user_input', content: query }]);
    const currentQuery = query;
    setQuery(''); // Clear input after sending

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      const response = await fetch('http://localhost:8000/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: currentQuery,
          agent_type: currentAgent 
        }),
        signal: abortController.signal
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to send query');
      }

      await handleStreamingResponse(response);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return;
      }
      console.error('Query failed:', error);
      const errorMessage = error instanceof Error ? error.message : 'Failed to process query. Please try again.';
      setMessages(prev => [...prev, { 
        type: 'error', 
        content: errorMessage 
      }]);
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  return (
    <div className="relative min-h-screen bg-gradient-to-b from-slate-950 via-indigo-950/20 to-black">
      <ParticlesBackground />
      
      {/* Header with Toggles */}
      <header className="fixed top-0 left-0 right-0 p-4 backdrop-blur-xl bg-black/30 z-50
                      border-b border-zinc-800/50 shadow-lg shadow-black/20">
        <div className="flex justify-between items-center max-w-[1600px] mx-auto">
          <h1 className="text-2xl font-bold bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 
                        text-transparent bg-clip-text animate-flow bg-[length:200%_auto]">
            WebRover
          </h1>
          
          <div className="flex-1 flex justify-center items-center">
            <div className="flex items-center space-x-24">
              <div className="flex flex-col items-center min-w-[280px]">
                <div className="flex items-center space-x-6">
                  <span className="text-zinc-400">Task</span>
                  <ToggleSwitch
                    enabled={isResearchMode}
                    onChange={setIsResearchMode}
                    label=""
                  />
                  <span className="text-zinc-400">Research</span>
                </div>
                <span className="text-xs text-zinc-500 mt-2">Switch between Task and Research agents</span>
              </div>
              
              <div className={`flex flex-col items-center min-w-[280px] transition-opacity duration-300 ${isResearchMode ? 'opacity-100' : 'opacity-0'}`}>
                <div className="flex items-center space-x-6">
                  <span className="text-zinc-400">Normal</span>
                  <ToggleSwitch
                    enabled={isDeepResearch}
                    onChange={setIsDeepResearch}
                    label=""
                  />
                  <span className="text-zinc-400">Deep Research</span>
                </div>
                <span className="text-xs text-zinc-500 mt-2">Enable comprehensive research mode</span>
              </div>
            </div>
          </div>

          <button
            onClick={handleDisconnect}
            className="px-4 py-2 rounded-full whitespace-nowrap
                     bg-gradient-to-r from-rose-500/10 to-pink-500/10
                     border border-rose-500/50 text-rose-400
                     hover:bg-rose-500/20 hover:border-rose-500/70 hover:text-rose-300
                     transition-all duration-300"
          >
            Disconnect Browser
          </button>
        </div>
      </header>

      {/* Input Bar */}
      <div className="fixed bottom-8 left-1/2 transform -translate-x-1/2 z-40 w-full max-w-[800px] px-4">
        <QueryInput
          value={query}
          onChange={setQuery}
          onSubmit={handleSubmit}
          onStop={handleStop}
          isLoading={isLoading}
        />
      </div>

      {/* Main Content */}
      <main className="relative pt-24 pb-32 z-10 overflow-y-auto h-[calc(100vh-140px)]">
        <div className="w-full pb-16">
          <ResponseDisplay messages={messages} />
        </div>
      </main>
    </div>
  );
}