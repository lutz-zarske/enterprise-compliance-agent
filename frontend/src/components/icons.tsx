import React from "react";

export interface IconProps extends React.SVGProps<SVGSVGElement> {
  size?: number | string;
}

/** Lucide-kompatible Strichsymbole ohne Zusatzabhaengigkeit. */
function icon(displayName: string, children: React.ReactNode) {
  const Component: React.FC<IconProps> = ({ size = 16, className = "", ...props }) => (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
  Component.displayName = displayName;
  return Component;
}

export const ShieldCheck = icon("ShieldCheck", <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="m9 12 2 2 4-4" /></>);
export const ShieldAlert = icon("ShieldAlert", <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="M12 8v4" /><path d="M12 16h.01" /></>);
export const RefreshCw = icon("RefreshCw", <><path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" /><path d="M8 16H3v5" /></>);
export const UploadCloud = icon("UploadCloud", <><path d="M4 14.9A7 7 0 1 1 15.7 8h1.8a4.5 4.5 0 0 1 2.5 8.2" /><path d="M12 12v9" /><path d="m16 16-4-4-4 4" /></>);
export const FileText = icon("FileText", <><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v4a2 2 0 0 0 2 2h4" /><path d="M10 9H8" /><path d="M16 13H8" /><path d="M16 17H8" /></>);
export const CheckCircle = icon("CheckCircle", <><circle cx="12" cy="12" r="10" /><path d="m9 12 2 2 4-4" /></>);
export const AlertTriangle = icon("AlertTriangle", <><path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></>);
export const XCircle = icon("XCircle", <><circle cx="12" cy="12" r="10" /><path d="m15 9-6 6" /><path d="m9 9 6 6" /></>);
export const MinusCircle = icon("MinusCircle", <><circle cx="12" cy="12" r="10" /><path d="M8 12h8" /></>);
export const Info = icon("Info", <><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></>);
export const Eye = icon("Eye", <><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></>);
export const EyeOff = icon("EyeOff", <><path d="M9.9 4.2A10 10 0 0 1 12 4c7 0 10 8 10 8a13 13 0 0 1-1.7 2.7" /><path d="M6.6 6.6A13 13 0 0 0 2 12s3 8 10 8a9.7 9.7 0 0 0 5.4-1.6" /><path d="M14.1 14.1a3 3 0 1 1-4.2-4.2" /><path d="m2 2 20 20" /></>);
export const Lock = icon("Lock", <><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></>);
export const Download = icon("Download", <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m7 10 5 5 5-5" /><path d="M12 15V3" /></>);
export const Copy = icon("Copy", <><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>);
export const Search = icon("Search", <><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></>);
export const Database = icon("Database", <><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14a9 3 0 0 0 18 0V5" /><path d="M3 12a9 3 0 0 0 18 0" /></>);
export const Server = icon("Server", <><rect x="2" y="2" width="20" height="8" rx="2" /><rect x="2" y="14" width="20" height="8" rx="2" /><path d="M6 6h.01" /><path d="M6 18h.01" /></>);
export const Scale = icon("Scale", <><path d="m16 16 3-8 3 8c-.9.7-1.9 1-3 1s-2.1-.3-3-1Z" /><path d="m2 16 3-8 3 8c-.9.7-1.9 1-3 1s-2.1-.3-3-1Z" /><path d="M7 21h10" /><path d="M12 3v18" /><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2" /></>);
export const Zap = icon("Zap", <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />);
export const Check = icon("Check", <path d="M20 6 9 17l-5-5" />);
export const X = icon("X", <><path d="M18 6 6 18" /><path d="m6 6 12 12" /></>);
export const Clock = icon("Clock", <><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></>);
export const Sun = icon("Sun", <><circle cx="12" cy="12" r="4" /><path d="M12 2v2" /><path d="M12 20v2" /><path d="m4.9 4.9 1.4 1.4" /><path d="m17.7 17.7 1.4 1.4" /><path d="M2 12h2" /><path d="M20 12h2" /><path d="m6.3 17.7-1.4 1.4" /><path d="m19.1 4.9-1.4 1.4" /></>);
export const Moon = icon("Moon", <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />);
export const Settings = icon("Settings", <><path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.5a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></>);
export const Pin = icon("Pin", <><path d="M12 17v5" /><path d="M9 10.8a2 2 0 0 1-1.1 1.8l-1.8.9A2 2 0 0 0 5 15.2V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.8a2 2 0 0 0-1.1-1.8l-1.8-.9A2 2 0 0 1 15 10.8V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z" /></>);
export const Send = icon("Send", <><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></>);
export const MessageSquare = icon("MessageSquare", <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />);
export const Printer = icon("Printer", <><path d="M6 9V2h12v7" /><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" /><rect x="6" y="14" width="12" height="8" rx="1" /></>);
export const Stamp = icon("Stamp", <><path d="M5 22h14" /><path d="M19.3 14.3A2.5 2.5 0 0 0 17.5 13h-2.8a1.6 1.6 0 0 1-1.6-1.6c0-.6.3-1.2.6-1.8a4 4 0 1 0-7.4 0c.3.6.6 1.2.6 1.8A1.6 1.6 0 0 1 5.3 13H6.5a2.5 2.5 0 0 0-2.5 2.5V17a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-1a2.5 2.5 0 0 0-.7-1.7Z" /></>);
export const Layers = icon("Layers", <><path d="m12.8 2.2a2 2 0 0 0-1.6 0L2.6 6.1a1 1 0 0 0 0 1.8l8.6 3.9a2 2 0 0 0 1.6 0l8.6-3.9a1 1 0 0 0 0-1.8Z" /><path d="m22 12-9.2 4.2a2 2 0 0 1-1.6 0L2 12" /><path d="m22 17-9.2 4.2a2 2 0 0 1-1.6 0L2 17" /></>);
export const Fingerprint = icon("Fingerprint", <><path d="M12 10a2 2 0 0 0-2 2c0 1 0 4-1 6" /><path d="M14 13.1c0 2.5 0 5-1 7.9" /><path d="M17.3 21.5c.1-.5.7-3.5.7-4.5" /><path d="M2 12a10 10 0 0 1 18-6" /><path d="M2 16h.01" /><path d="M21.8 16c.2-2 .1-5.4 0-6" /><path d="M5 19.5C5.5 18 6 15 6 12a6 6 0 0 1 .3-2" /><path d="M8.7 22c.2-.7.5-1.3.6-2" /><path d="M9 6.8a6 6 0 0 1 9 5.2v2" /></>);
export const Hash = icon("Hash", <><path d="M4 9h16" /><path d="M4 15h16" /><path d="M10 3 8 21" /><path d="M16 3l-2 18" /></>);
export const Calculator = icon("Calculator", <><rect x="4" y="2" width="16" height="20" rx="2" /><path d="M8 6h8" /><path d="M16 14v4" /><path d="M16 10h.01" /><path d="M12 10h.01" /><path d="M8 10h.01" /><path d="M12 14h.01" /><path d="M8 14h.01" /><path d="M12 18h.01" /><path d="M8 18h.01" /></>);
export const WifiOff = icon("WifiOff", <><path d="M12 20h.01" /><path d="M8.5 16.4a5 5 0 0 1 7 0" /><path d="M2 8.8a15 15 0 0 1 4.2-2.6" /><path d="M10.7 5.1A15 15 0 0 1 22 8.8" /><path d="M5 12.9a10 10 0 0 1 5.2-2.7" /><path d="M16.8 13.6a10 10 0 0 1 2.2 1.3" /><path d="m2 2 20 20" /></>);
export const ChevronRight = icon("ChevronRight", <path d="m9 18 6-6-6-6" />);
export const Cpu = icon("Cpu", <><rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /><path d="M15 2v2" /><path d="M15 20v2" /><path d="M2 15h2" /><path d="M2 9h2" /><path d="M20 15h2" /><path d="M20 9h2" /><path d="M9 2v2" /><path d="M9 20v2" /></>);
export const Terminal = icon("Terminal", <><path d="m4 17 6-6-6-6" /><path d="M12 19h8" /></>);
export const Package = icon("Package", <><path d="M11 21.7a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7z" /><path d="M12 22V12" /><path d="m3.3 7 7.7 4.7a2 2 0 0 0 2 0L20.7 7" /><path d="m7.5 4.3 9 5.1" /></>);
export const FileCode = icon("FileCode", <><path d="M10 12.5 8 15l2 2.5" /><path d="m14 12.5 2 2.5-2 2.5" /><path d="M14 2v4a2 2 0 0 0 2 2h4" /><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" /></>);
