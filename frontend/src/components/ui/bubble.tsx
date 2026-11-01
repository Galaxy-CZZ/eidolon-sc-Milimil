import * as React from "react"
import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

function BubbleGroup({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="bubble-group"
      className={cn("flex min-w-0 flex-col gap-2", className)}
      {...props}
    />
  )
}

const bubbleVariants = cva(
  "group/bubble relative flex w-fit max-w-[80%] min-w-0 flex-col gap-1 group-data-[align=end]/message:self-end data-[align=end]:self-end data-[variant=ghost]:max-w-full",
  {
    variants: {
      variant: {
        default:
          "*:data-[slot=bubble-content]:bg-primary *:data-[slot=bubble-content]:text-primary-foreground [&>[data-slot=bubble-content]:is(button,a):hover]:bg-primary/80",
        // eidolon: 悬停色原来是任意值里的 color-mix(…var(--secondary)…)；任意值里不写颜色（frontend/AGENTS.md），改用 /80。
        secondary:
          "*:data-[slot=bubble-content]:bg-secondary *:data-[slot=bubble-content]:text-secondary-foreground [&>[data-slot=bubble-content]:is(button,a):hover]:bg-secondary/80",
        muted:
          "*:data-[slot=bubble-content]:bg-muted [&>[data-slot=bubble-content]:is(button,a):hover]:bg-muted/80",
        // eidolon: 删掉 tinted：它在任意值里用相对颜色语法从 --primary 临时推色，违反 DESIGN.md「The Paired Colour Rule」，
        // 她颜色的底只取 imageColorScale() 的成对值。
        outline:
          "*:data-[slot=bubble-content]:border-border *:data-[slot=bubble-content]:bg-background [&>[data-slot=bubble-content]:is(button,a):hover]:bg-muted [&>[data-slot=bubble-content]:is(button,a):hover]:text-foreground dark:[&>[data-slot=bubble-content]:is(button,a):hover]:bg-input/30",
        ghost:
          "border-none *:data-[slot=bubble-content]:rounded-none *:data-[slot=bubble-content]:bg-transparent *:data-[slot=bubble-content]:p-0 [&>[data-slot=bubble-content]:is(button,a):hover]:bg-muted [&>[data-slot=bubble-content]:is(button,a):hover]:text-foreground dark:[&>[data-slot=bubble-content]:is(button,a):hover]:bg-muted/50",
        destructive:
          "*:data-[slot=bubble-content]:bg-destructive/10 *:data-[slot=bubble-content]:text-destructive dark:*:data-[slot=bubble-content]:bg-destructive/20 [&>[data-slot=bubble-content]:is(button,a):hover]:bg-destructive/20 dark:[&>[data-slot=bubble-content]:is(button,a):hover]:bg-destructive/30",
        // eidolon: 对话页的两种气泡（DESIGN.md「Chat bubbles」）：22px 圆角、没有尾巴、不投影。
        // 她的：浅色白底、深色 her-bubble-night，最宽 min(30rem, 72vw)；制作人的：事务所深蓝墨水，最宽 72%。
        // 字号由气泡里的内容自己定（原文和字幕字号不同）。
        // 她的气泡能拿到焦点时（键盘打开「朗读」菜单，GLOSSARY.md「朗读」），焦点环画在内容那一块上，跟着气泡的圆角。
        her: "max-w-[min(30rem,72vw)] outline-none *:data-[slot=bubble-content]:rounded-bubble *:data-[slot=bubble-content]:bg-bubble-her *:data-[slot=bubble-content]:px-4 *:data-[slot=bubble-content]:text-foreground focus-visible:*:data-[slot=bubble-content]:ring-3 focus-visible:*:data-[slot=bubble-content]:ring-ring/50",
        producer:
          "max-w-[72%] *:data-[slot=bubble-content]:rounded-bubble *:data-[slot=bubble-content]:bg-producer-ink *:data-[slot=bubble-content]:px-4 *:data-[slot=bubble-content]:text-on-producer-ink",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Bubble({
  variant = "default",
  align = "start",
  joinsPrevious = false,
  joinsNext = false,
  className,
  ...props
}: React.ComponentProps<"div"> &
  VariantProps<typeof bubbleVariants> & {
    align?: "start" | "end"
    // eidolon: The Bubble Group Rule（DESIGN.md）：同一个人连着发的几条成一组，组内相邻气泡靠内侧的角收成 rounded-md。
    // joinsPrevious：上面紧挨着同一组的一条（收内侧上角）；joinsNext：下面还有（收内侧下角）。
    joinsPrevious?: boolean
    joinsNext?: boolean
  }) {
  return (
    <div
      data-slot="bubble"
      data-variant={variant}
      data-align={align}
      data-joins-previous={joinsPrevious || undefined}
      data-joins-next={joinsNext || undefined}
      className={cn(
        bubbleVariants({ variant }),
        "data-joins-previous:data-[align=start]:*:data-[slot=bubble-content]:rounded-tl-md data-joins-next:data-[align=start]:*:data-[slot=bubble-content]:rounded-bl-md data-joins-previous:data-[align=end]:*:data-[slot=bubble-content]:rounded-tr-md data-joins-next:data-[align=end]:*:data-[slot=bubble-content]:rounded-br-md",
        className
      )}
      {...props}
    />
  )
}

function BubbleContent({
  className,
  render,
  ...props
}: useRender.ComponentProps<"div">) {
  return useRender({
    defaultTagName: "div",
    props: mergeProps<"div">(
      {
        className: cn(
          "w-fit max-w-full min-w-0 overflow-hidden rounded-xl border border-transparent px-3 py-2 text-sm leading-relaxed wrap-break-word group-data-[align=end]/bubble:self-end [button]:text-left [button,a]:transition-colors [button,a]:outline-none [button,a]:focus-visible:border-ring [button,a]:focus-visible:ring-3 [button,a]:focus-visible:ring-ring/50",
          className
        ),
      },
      props
    ),
    render,
    state: {
      slot: "bubble-content",
    },
  })
}

const bubbleReactionsVariants = cva(
  "absolute z-10 flex w-fit shrink-0 items-center justify-center gap-1 rounded-full bg-muted px-1.5 py-0.5 text-sm ring-3 ring-card has-[button]:p-0",
  {
    variants: {
      side: {
        top: "top-0 -translate-y-3/4",
        bottom: "bottom-0 translate-y-3/4",
      },
      align: {
        start: "left-3",
        end: "right-3",
      },
    },
    defaultVariants: {
      side: "bottom",
      align: "end",
    },
  }
)

function BubbleReactions({
  side = "bottom",
  align = "end",
  className,
  ...props
}: React.ComponentProps<"div"> & {
  align?: "start" | "end"
  side?: "top" | "bottom"
}) {
  return (
    <div
      data-slot="bubble-reactions"
      data-align={align}
      data-side={side}
      className={cn(bubbleReactionsVariants({ side, align }), className)}
      {...props}
    />
  )
}

export { BubbleGroup, Bubble, BubbleContent, BubbleReactions }
