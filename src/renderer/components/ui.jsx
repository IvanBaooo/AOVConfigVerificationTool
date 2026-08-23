import { PackageOpen } from "lucide-react";

export const cn = (...values) => values.filter(Boolean).join(" ");

export function Button({ variant = "outline", size = "default", icon: Icon, children, className, ...props }) {
  return (
    <button className={cn("button", `button-${variant}`, `button-${size}`, className)} {...props}>
      {Icon ? <Icon size={size === "icon" ? 16 : 15} strokeWidth={1.8} /> : null}
      {children}
    </button>
  );
}

export function Card({ className, children, ...props }) {
  return <section className={cn("card", className)} {...props}>{children}</section>;
}

export function Field({ label, hint, className, children }) {
  return (
    <label className={cn("field", className)}>
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

export function Segmented({ value, options, onChange, ariaLabel }) {
  return (
    <div className="segmented" role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={cn(value === option.value && "selected")}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Badge({ tone = "neutral", children, icon: Icon }) {
  return <span className={cn("badge", `badge-${tone}`)}>{Icon ? <Icon size={13} /> : null}{children}</span>;
}

export function StatusDot({ status = "idle" }) {
  return <span className={cn("status-dot", `status-${status}`)} />;
}

export function SectionHeading({ eyebrow, title, description, action }) {
  return (
    <div className="section-heading">
      <div>
        {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
        <h2>{title}</h2>
        {description ? <p>{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ icon: Icon = PackageOpen, title, description }) {
  return (
    <div className="empty-state">
      <div className="empty-icon"><Icon size={20} /></div>
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}
