import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import remarkGfm from 'remark-gfm';
import { motion, AnimatePresence } from 'framer-motion';
import { useEffect, useMemo, useRef } from 'react';
import type { Components } from 'react-markdown';
import { ResponseActions } from './ResponseActions';

interface Message {
  type: 'thought' | 'action' | 'dom_update' | 'interaction' | 'browser_action' | 
        'rag_action' | 'review' | 'close_tab' | 'subtopics' | 'subtopic_answer' |
        'subtopic_status' | 'compile' | 'final_answer' | 'conversation_history' |
        'cleanup' | 'error' | 'final_response' | 'user_input';
  content: string;
}

interface ResponseDisplayProps {
  messages: Message[];
}

// Helper function to stringify message content
const formatMessageContent = (content: unknown) => {
  if (Array.isArray(content)) {
    return content.join('\n');
  }
  
  if (typeof content === 'string') {
    try {
      // Try to parse as JSON in case it's a stringified array
      const parsed = JSON.parse(content);
      if (Array.isArray(parsed)) {
        return parsed.join('\n');
      }
    } catch {
      // If parsing fails, return as is
      return content;
    }
  }
  
  return String(content ?? '');
};

export const markdownComponents: Components = {
  h1: ({ children, ...props }) => (
    <h1 className="text-3xl font-bold mt-8 mb-6 bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 
                   text-transparent bg-clip-text" {...props}>
      {children}
    </h1>
  ),
  h2: ({ children, ...props }) => (
    <h2 className="text-2xl font-semibold mt-6 mb-4 text-indigo-300 
                   border-b border-indigo-500/20 pb-2" {...props}>
      {children}
    </h2>
  ),
  h3: ({ children, ...props }) => (
    <h3 className="text-xl font-medium mt-4 mb-3 text-purple-300" {...props}>
      {children}
    </h3>
  ),
  p: ({ children, ...props }) => (
    <p className="text-zinc-100 leading-7 mb-4" {...props}>
      {children}
    </p>
  ),
  ul: ({ children, ...props }) => (
    <ul className="my-4 space-y-2 list-none" {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }) => (
    <ol className="my-4 space-y-2 list-decimal pl-4" {...props}>
      {children}
    </ol>
  ),
  li: ({ children, ...props }) => (
    <li className="flex items-start" {...props}>
      <span className="text-indigo-400 mr-2 font-bold">•</span>
      <span className="text-zinc-100">{children}</span>
    </li>
  ),
  blockquote: ({ children, ...props }) => (
    <blockquote className="border-l-4 border-indigo-500/50 bg-indigo-500/5 
                          pl-6 py-4 my-6 rounded-r-lg italic text-zinc-300" {...props}>
      {children}
    </blockquote>
  ),
  code: ({ className, children, ...props }) => {
    const isInline = 'inline' in props ? Boolean(props.inline) : false;
    const match = /language-(\w+)/.exec(String(className || ''));
    return !isInline && match ? (
      <SyntaxHighlighter
        style={oneDark}
        language={match[1]}
        PreTag="div"
        className="!my-8 rounded-xl border border-white/10 !bg-zinc-900/50 !p-6"
      >
        {String(children).replace(/\n$/, '')}
      </SyntaxHighlighter>
    ) : (
      <code className="bg-zinc-800/50 px-2 py-1 rounded-md font-mono text-sm text-indigo-300" {...props}>
        {children}
      </code>
    );
  },
  table: ({ children, ...props }) => (
    <div className="overflow-x-auto my-6">
      <table className="w-full border-collapse" {...props}>
        {children}
      </table>
    </div>
  ),
  th: ({ children, ...props }) => (
    <th className="text-left py-2 px-4 border-b border-zinc-800 text-indigo-300 font-semibold" {...props}>
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td className="py-2 px-4 border-b border-zinc-800/50 text-zinc-100" {...props}>
      {children}
    </td>
  ),
  a: ({ children, href, ...props }) => (
    <a 
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-indigo-400 hover:text-purple-400 underline decoration-indigo-500/30 
                hover:decoration-purple-500/50 decoration-2 underline-offset-2 
                transition-all duration-200 font-medium
                hover:scale-[1.02] inline-flex items-center gap-0.5" 
      {...props}
    >
      {children}
      <svg 
        className="w-3.5 h-3.5 ml-1 -mt-0.5 opacity-70" 
        fill="none" 
        viewBox="0 0 24 24" 
        stroke="currentColor"
      >
        <path 
          strokeLinecap="round" 
          strokeLinejoin="round" 
          strokeWidth={2} 
          d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" 
        />
      </svg>
    </a>
  ),
};

export function ResponseDisplay({ messages }: ResponseDisplayProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    if (messagesEndRef.current) {
      const container = messagesEndRef.current.parentElement?.parentElement?.parentElement;
      container?.scrollTo({
        top: container.scrollHeight,
        behavior: 'smooth',
      });
    }
  };

  // Scroll on new messages with a slight delay to ensure content is rendered
  useEffect(() => {
    const timeoutId = setTimeout(scrollToBottom, 100);
    return () => clearTimeout(timeoutId);
  }, [messages]);

  // Group messages by conversation turns
  const messageGroups = useMemo(() => {
    const groups: Message[][] = [];
    let currentGroup: Message[] = [];
    
    messages.forEach((message) => {
      if (message.type === 'user_input') {
        if (currentGroup.length > 0) {
          groups.push(currentGroup);
        }
        currentGroup = [message];
      } else {
        currentGroup.push(message);
      }
    });
    
    if (currentGroup.length > 0) {
      groups.push(currentGroup);
    }
    
    return groups;
  }, [messages]);

  return (
    <div className="w-full max-w-6xl mx-auto space-y-8 px-4">
      <AnimatePresence mode="popLayout">
        {messageGroups.map((group, groupIndex) => {
          const userMessage = group.find(m => m.type === 'user_input');
          const finalMessage = group.find(m => 
            m.type === 'final_answer' || m.type === 'final_response'
          );
          const streamingMessages = !finalMessage ? group.filter(m => 
            m.type !== 'user_input' && 
            m.type !== 'final_answer' && 
            m.type !== 'final_response'
          ) : [];

          return (
            <motion.div
              key={`group-${groupIndex}`}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="space-y-4"
            >
              {/* User Message */}
              {userMessage && (
                <motion.div
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex justify-end"
                >
                  <div className="max-w-[90%] md:max-w-[75%] break-words bg-gradient-to-r from-indigo-500/20 
                              via-purple-500/20 to-pink-500/20 backdrop-blur-sm border border-indigo-500/30 
                              rounded-2xl rounded-tr-sm px-5 py-3 shadow-lg shadow-purple-500/10">
                    <p className="text-sm font-medium text-white/90 whitespace-pre-wrap">
                      {formatMessageContent(userMessage.content)}
                    </p>
                  </div>
                </motion.div>
              )}

              {/* Streaming Messages */}
              {streamingMessages.length > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="space-y-2"
                >
                  {streamingMessages.map((message, index) => (
                    <motion.div
                      key={`stream-${groupIndex}-${index}`}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -20 }}
                      className="flex justify-start"
                    >
                      <div className={`max-w-[90%] md:max-w-[75%] break-words backdrop-blur-sm border 
                        px-4 py-2 rounded-xl rounded-tl-sm
                        ${message.type === 'error'
                          ? 'bg-rose-500/10 border-rose-500/30 shadow-rose-500/20 text-rose-300'
                          : message.type.includes('action') 
                            ? 'bg-emerald-500/10 border-emerald-500/30 shadow-emerald-500/20' 
                            : 'bg-zinc-500/10 border-zinc-500/30 shadow-zinc-500/20'} 
                        shadow-lg`}>
                        <p className="text-sm text-white/70 whitespace-pre-wrap">
                          {formatMessageContent(message.content)}
                        </p>
                      </div>
                    </motion.div>
                  ))}
                </motion.div>
              )}

              {/* Final Response */}
              {finalMessage && (
                <motion.div
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex flex-col justify-start"
                >
                  <div className="max-w-[95%] md:max-w-[85%] break-words bg-gradient-to-br from-indigo-500/20 
                              via-purple-500/20 to-pink-500/20 backdrop-blur-sm border border-indigo-500/30 
                              rounded-2xl rounded-tl-sm px-6 py-4 shadow-xl shadow-indigo-500/20">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={markdownComponents}
                      className="prose prose-invert max-w-none space-y-4 overflow-x-hidden"
                    >
                      {formatMessageContent(finalMessage.content)}
                    </ReactMarkdown>
                    <ResponseActions 
                      content={formatMessageContent(finalMessage.content)}
                      isResearchResponse={finalMessage.type === 'final_response' || finalMessage.type === 'final_answer'}
                    />
                  </div>
                </motion.div>
              )}
            </motion.div>
          );
        })}
      </AnimatePresence>
      <div ref={messagesEndRef} className="h-px" />
    </div>
  );
}