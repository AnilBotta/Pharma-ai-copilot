"use client";

import * as React from "react";
import { ArrowUp, FileUp, Paperclip, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { projects } from "@/lib/data";

export function ChatComposer({
  onSend,
  disabled,
  placeholder = "Ask about patents, literature, or development strategy…",
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [value, setValue] = React.useState("");
  const [project, setProject] = React.useState<string>(projects[0]?.id ?? "prj-1");
  const [file, setFile] = React.useState<File | null>(null);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
      inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 180)}px`;
    }
  }, [value]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue("");
    setFile(null);
  }

  return (
    <div className="glass-strong relative rounded-2xl p-2.5 shadow-xl shadow-blue-900/5 focus-within:ring-2 focus-within:ring-blue-500/20">
      {file && (
        <div className="mb-2 flex items-center gap-2 rounded-lg border border-blue-500/25 bg-blue-500/5 px-3 py-2">
          <FileUp className="size-4 shrink-0 text-blue-600 dark:text-blue-400" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium">{file.name}</p>
            <p className="text-[10px] text-muted-foreground">
              {(file.size / 1024).toFixed(0)} KB · will be referenced as grounding
            </p>
          </div>
          <button
            onClick={() => setFile(null)}
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Remove attachment"
          >
            <X className="size-3.5" />
          </button>
        </div>
      )}

      <div className="flex items-end gap-2">
        <div className="flex flex-col gap-1.5 py-1">
          <label className="cursor-pointer rounded-lg p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground" title="Upload PDF">
            <input
              type="file"
              accept=".pdf,.doc,.docx"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) setFile(f);
                e.target.value = "";
              }}
            />
            <Paperclip className="size-[18px]" />
          </label>
        </div>

        <textarea
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          className="max-h-44 flex-1 resize-none bg-transparent px-1 py-2 text-sm outline-none placeholder:text-muted-foreground"
        />

        <Button
          size="icon"
          onClick={submit}
          disabled={!value.trim() || disabled}
          className="mb-0.5 size-9 rounded-xl"
          aria-label="Send message"
        >
          <ArrowUp className="size-4" />
        </Button>
      </div>

      <div className="mt-1.5 flex items-center justify-between px-1.5 pb-0.5">
        <Select value={project} onValueChange={setProject}>
          <SelectTrigger size="sm" className="h-7 gap-1 rounded-md border-none bg-transparent px-2 text-[11px] shadow-none dark:bg-transparent">
            <SelectValue placeholder="Project" />
          </SelectTrigger>
          <SelectContent>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[10px] text-muted-foreground">
          Enter to send · Shift+Enter for newline
        </p>
      </div>
    </div>
  );
}