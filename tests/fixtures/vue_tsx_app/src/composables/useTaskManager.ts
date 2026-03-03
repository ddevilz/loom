import { ref, computed, Ref } from 'vue';
import { Task, TaskFilter, TaskStatus, TaskUpdatePayload } from '../types/Task';

export function useTaskManager() {
  const tasks: Ref<Task[]> = ref([]);
  const filter: Ref<TaskFilter> = ref({});
  const isLoading = ref(false);

  const filteredTasks = computed(() => {
    return tasks.value.filter(task => {
      if (filter.value.status && !filter.value.status.includes(task.status)) {
        return false;
      }
      if (filter.value.priority && !filter.value.priority.includes(task.priority)) {
        return false;
      }
      if (filter.value.assignee && task.assignee !== filter.value.assignee) {
        return false;
      }
      if (filter.value.searchQuery) {
        const query = filter.value.searchQuery.toLowerCase();
        return task.title.toLowerCase().includes(query) ||
               task.description.toLowerCase().includes(query);
      }
      return true;
    });
  });

  const tasksByStatus = computed(() => {
    const grouped: Record<TaskStatus, Task[]> = {
      [TaskStatus.TODO]: [],
      [TaskStatus.IN_PROGRESS]: [],
      [TaskStatus.DONE]: [],
      [TaskStatus.ARCHIVED]: []
    };

    filteredTasks.value.forEach(task => {
      grouped[task.status].push(task);
    });

    return grouped;
  });

  async function fetchTasks(): Promise<void> {
    isLoading.value = true;
    try {
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 500));
      tasks.value = [];
    } finally {
      isLoading.value = false;
    }
  }

  function addTask(task: Omit<Task, 'id' | 'createdAt' | 'updatedAt'>): void {
    const newTask: Task = {
      ...task,
      id: crypto.randomUUID(),
      createdAt: new Date(),
      updatedAt: new Date()
    };
    tasks.value.push(newTask);
  }

  function updateTask(id: string, updates: TaskUpdatePayload): void {
    const index = tasks.value.findIndex(t => t.id === id);
    if (index !== -1) {
      tasks.value[index] = {
        ...tasks.value[index],
        ...updates,
        updatedAt: new Date()
      };
    }
  }

  function deleteTask(id: string): void {
    tasks.value = tasks.value.filter(t => t.id !== id);
  }

  function setFilter(newFilter: TaskFilter): void {
    filter.value = newFilter;
  }

  return {
    tasks,
    filteredTasks,
    tasksByStatus,
    isLoading,
    fetchTasks,
    addTask,
    updateTask,
    deleteTask,
    setFilter
  };
}
