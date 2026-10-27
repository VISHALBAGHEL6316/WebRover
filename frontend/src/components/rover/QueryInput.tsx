import { useRef } from 'react';

interface QueryInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  isLoading: boolean;
}

export function QueryInput({ value, onChange, onSubmit, onStop, isLoading }: QueryInputProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea height
  const adjustHeight = () => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = `${inputRef.current.scrollHeight}px`;
    }
  };

  // Handle input change
  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value);
    adjustHeight();
  };

  // Handle key press
  const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className="fixed bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-black via-black/95 to-transparent">
      <div className="max-w-4xl mx-auto pb-2">
        <div className="relative flex items-start">
          <textarea
            ref={inputRef}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyPress}
            placeholder="Ask WebRover anything..."
            rows={1}
            className="w-full px-6 py-4 pr-24 bg-zinc-900/50 backdrop-blur-sm 
                     border border-zinc-800 rounded-2xl
                     text-zinc-100 placeholder-zinc-500
                     focus:outline-none focus:ring-2 focus:ring-purple-500/50
                     focus:border-purple-500/50
                     hover:border-zinc-700 transition-all duration-300
                     resize-none overflow-hidden min-h-[60px] max-h-[120px]"
          />
          
          {isLoading ? (
            <button
              onClick={onStop}
              type="button"
              className="absolute right-2 top-2 px-5 py-2.5 
                       bg-gradient-to-r from-red-600 to-rose-600
                       hover:from-red-500 hover:to-rose-500
                       rounded-xl text-white font-medium text-sm
                       shadow-lg shadow-red-500/25
                       transform hover:scale-[1.02] active:scale-[0.98]
                       transition-all duration-300 flex items-center gap-2 cursor-pointer"
              title="Stop model execution"
            >
              <span className="w-2.5 h-2.5 rounded-xs bg-white animate-pulse" />
              <span>Stop</span>
            </button>
          ) : (
            <button
              onClick={onSubmit}
              disabled={!value.trim()}
              className="absolute right-2 top-2 px-6 py-2.5 
                       bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500
                       rounded-xl text-white font-medium
                       hover:opacity-90 hover:shadow-lg hover:shadow-purple-500/25
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transform hover:scale-[1.02] active:scale-[0.98]
                       transition-all duration-300"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  );
} 