# ✨ Vibecoding stuff ✨

If you are curious on how I did this project, and which prompts were used, this is the right place.

## Model info

The project was almost 100% developed using GitHub Copilot, mostly by iterating on prompts and refining the output. I used Claude Sonnet 4.6 most of the time for generating and refining prompts.

## Full code iterations

Here is a list of the whole conversations while implementing different features:

- [Initial release](./first-release.md): This is where it all started, you can see the initial request with the specifications, which were used to create the first [specs file](https://github.com/iu2frl/CloudShell/blob/6915981f642e396b378081f709936882f77e0235/.github/copilot-instructions.md.md)
  - When the project became more defined, I started breaking down the features into smaller tasks and creating issues for each one.
  - The specs file was then split into the [main README](../../README.md) and the [copilot-instructions](../../.github/copilot-instructions.md) file, which is where I keep the detailed instructions for Copilot.
  - The specs file included a set of milestones numbered from M1 to M7 which I started flagging as soon as the copilot was able to implement them.
- [UI improvements](./ui-improvement-v1.md): This is where I documented some of the changes made to the user interface, like moving the change password button to a dedicated location.
- [Audit logging](./audit-logging.md): This is where I documented the implementation of audit logging for tracking user actions.
- [Unit testing](./unit-testing.md): This is where I documented the implementation of unit tests for the backend and frontend.
- [File manager](./file-manager-v1.md): This is where I documented the implementation of the file manager feature.

## Why vibecoding?

I already know Python and Typescript as I use them in my job, so it was a good excercise to see how I could leverage my existing knowledge while learning more about the capabilities of AI in coding.

## Any suggestions?

As AI is getting more and more into the hobbyist space, I think it would be great to see more tools and resources aimed at helping developers integrate AI into their workflows. This could include better documentation, more examples, and even dedicated AI coding environments.

I hope this documentation can help you understand the process and inspire you to explore the possibilities of AI in your own projects.
