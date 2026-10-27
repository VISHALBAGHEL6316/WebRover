import { useState } from 'react';
import { CheckIcon, DocumentIcon, ArrowDownTrayIcon } from '@heroicons/react/24/outline';
import { jsPDF } from 'jspdf';

interface ResponseActionsProps {
  content: string;
  isResearchResponse: boolean;
}

export function ResponseActions({ content, isResearchResponse }: ResponseActionsProps) {
  const [copying, setCopying] = useState(false);
  const [typing, setTyping] = useState(false);

  const handleCopy = async () => {
    try {
      setCopying(true);
      await navigator.clipboard.writeText(content);
      setTimeout(() => setCopying(false), 1000);
    } catch (error) {
      console.error('Failed to copy:', error);
      setCopying(false);
    }
  };

  const handleTypeInDocs = async () => {
    try {
      setTyping(true);
      const response = await fetch('http://localhost:8000/api/docs/type', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to type in docs');
      }

      const data = await response.json();
      console.log('Type in docs response:', data);
    } catch (error) {
      console.error('Failed to type in docs:', error);
    } finally {
      setTyping(false);
    }
  };

  const handleDownloadPDF = async () => {
    try {
      const pdf = new jsPDF({
        unit: 'pt',
        format: 'a4',
        hotfixes: ['px_scaling']
      });

      const pageWidth = pdf.internal.pageSize.width;
      const pageHeight = pdf.internal.pageSize.height;
      let y = 50;
      const margin = 50;
      const maxWidth = pageWidth - (margin * 2);
      
      const splitTextToSize = (text: string, fontSize: number) => {
        pdf.setFontSize(fontSize);
        return pdf.splitTextToSize(text, maxWidth);
      };

      const checkNewPage = (requiredHeight: number) => {
        if (y + requiredHeight > pageHeight - margin) {
          pdf.addPage();
          y = 50;
          return true;
        }
        return false;
      };

      const lines = content.split('\n');
      lines.forEach(line => {
        pdf.setFont('helvetica', 'normal');
        
        if (line.startsWith('# ')) {
          checkNewPage(40);
          pdf.setFontSize(20);
          pdf.setFont('helvetica', 'bold');
          const text = line.replace('# ', '');
          const wrappedText = splitTextToSize(text, 20);
          y += 20;
          wrappedText.forEach((textLine: string) => {
            pdf.text(textLine, margin, y);
            y += 25;
          });
        } else if (line.startsWith('## ')) {
          checkNewPage(35);
          pdf.setFontSize(16);
          pdf.setFont('helvetica', 'bold');
          const text = line.replace('## ', '');
          const wrappedText = splitTextToSize(text, 16);
          y += 15;
          wrappedText.forEach((textLine: string) => {
            pdf.text(textLine, margin, y);
            y += 20;
          });
        } else if (line.startsWith('### ')) {
          checkNewPage(30);
          pdf.setFontSize(14);
          pdf.setFont('helvetica', 'bold');
          const text = line.replace('### ', '');
          const wrappedText = splitTextToSize(text, 14);
          y += 15;
          wrappedText.forEach((textLine: string) => {
            pdf.text(textLine, margin, y);
            y += 15;
          });
        } else if (line.startsWith('- ')) {
          checkNewPage(25);
          pdf.setFontSize(11);
          const text = line.replace('- ', '');
          const wrappedText = splitTextToSize(text, 11);
          y += 15;
          pdf.circle(margin + 3, y - 4, 1.5, 'F');
          pdf.text(wrappedText, margin + 10, y);
          y += (wrappedText.length - 1) * 15;
        } else if (line.trim().length > 0) {
          checkNewPage(25);
          pdf.setFontSize(11);
          const wrappedText = splitTextToSize(line, 11);
          y += 15;
          pdf.text(wrappedText, margin, y);
          y += (wrappedText.length - 1) * 15;
        } else {
          y += 10;
        }
      });

      pdf.save('webrover-research.pdf');
    } catch (error) {
      console.error('Failed to generate PDF:', error);
    }
  };

  return (
    <div className="flex items-center gap-2 mt-4">
      <button
        onClick={handleCopy}
        className="px-3 py-1.5 text-xs rounded-lg bg-zinc-800/50 hover:bg-zinc-700/50 
                 border border-zinc-700/50 text-zinc-300 transition-all duration-200
                 flex items-center gap-1.5"
      >
        {copying ? <CheckIcon className="w-3.5 h-3.5" /> : <DocumentIcon className="w-3.5 h-3.5" />}
        {copying ? 'Copied!' : 'Copy'}
      </button>
      
      {isResearchResponse && (
        <button
          onClick={handleTypeInDocs}
          disabled={typing}
          className="px-3 py-1.5 text-xs rounded-lg bg-zinc-800/50 hover:bg-zinc-700/50 
                   border border-zinc-700/50 text-zinc-300 transition-all duration-200
                   flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <DocumentIcon className="w-3.5 h-3.5" />
          {typing ? 'Typing...' : 'Type in Docs'}
        </button>
      )}
      
      <button
        onClick={handleDownloadPDF}
        className="px-3 py-1.5 text-xs rounded-lg bg-zinc-800/50 hover:bg-zinc-700/50 
                 border border-zinc-700/50 text-zinc-300 transition-all duration-200
                 flex items-center gap-1.5"
      >
        <ArrowDownTrayIcon className="w-3.5 h-3.5" />
        Download PDF
      </button>

    </div>
  );
} 