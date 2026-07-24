"""Security: treating the open web as the adversarial input it is.

Web pages are written by people who may know an agent will read them. Reviews,
alt text, hidden divs and HTML comments are all places an instruction can be
planted for whatever model processes the page.

The defence has two halves and the second is the one most projects skip:
wrap untrusted content so a model treats it as data, and then **count what you
caught**. Injection-detection recall is a number that goes in the README.
"""
