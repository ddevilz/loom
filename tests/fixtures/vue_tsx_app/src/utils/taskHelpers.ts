import { Task, TaskStatus, TaskPriority } from '../types/Task';

export function sortTasksByPriority(tasks: Task[]): Task[] {
  const priorityOrder = {
    [TaskPriority.URGENT]: 0,
    [TaskPriority.HIGH]: 1,
    [TaskPriority.MEDIUM]: 2,
    [TaskPriority.LOW]: 3
  };

  return [...tasks].sort((a, b) => {
    return priorityOrder[a.priority] - priorityOrder[b.priority];
  });
}

export function sortTasksByDueDate(tasks: Task[]): Task[] {
  return [...tasks].sort((a, b) => {
    if (!a.dueDate) return 1;
    if (!b.dueDate) return -1;
    return a.dueDate.getTime() - b.dueDate.getTime();
  });
}

export function getOverdueTasks(tasks: Task[]): Task[] {
  const now = new Date();
  return tasks.filter(task => {
    return task.dueDate && 
           task.dueDate < now && 
           task.status !== TaskStatus.DONE &&
           task.status !== TaskStatus.ARCHIVED;
  });
}

export function getTaskCompletionRate(tasks: Task[]): number {
  if (tasks.length === 0) return 0;
  const completed = tasks.filter(t => t.status === TaskStatus.DONE).length;
  return (completed / tasks.length) * 100;
}

export class TaskValidator {
  static validateTitle(title: string): boolean {
    return title.trim().length >= 3 && title.length <= 100;
  }

  static validateDescription(description: string): boolean {
    return description.length <= 500;
  }

  static validateTask(task: Partial<Task>): string[] {
    const errors: string[] = [];

    if (task.title && !this.validateTitle(task.title)) {
      errors.push('Title must be between 3 and 100 characters');
    }

    if (task.description && !this.validateDescription(task.description)) {
      errors.push('Description must be less than 500 characters');
    }

    return errors;
  }
}
