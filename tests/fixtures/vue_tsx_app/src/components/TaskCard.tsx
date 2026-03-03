import { defineComponent, PropType } from 'vue';
import { Task, TaskStatus, TaskPriority } from '../types/Task';

interface TaskCardProps {
  task: Task;
  onUpdate?: (task: Task) => void;
  onDelete?: (id: string) => void;
}

export const TaskCard = defineComponent({
  name: 'TaskCard',
  
  props: {
    task: {
      type: Object as PropType<Task>,
      required: true
    },
    onUpdate: {
      type: Function as PropType<(task: Task) => void>,
      required: false
    },
    onDelete: {
      type: Function as PropType<(id: string) => void>,
      required: false
    }
  },

  setup(props) {
    const getPriorityColor = (priority: TaskPriority): string => {
      const colors = {
        [TaskPriority.LOW]: 'bg-blue-100',
        [TaskPriority.MEDIUM]: 'bg-yellow-100',
        [TaskPriority.HIGH]: 'bg-orange-100',
        [TaskPriority.URGENT]: 'bg-red-100'
      };
      return colors[priority];
    };

    const getStatusLabel = (status: TaskStatus): string => {
      const labels = {
        [TaskStatus.TODO]: 'To Do',
        [TaskStatus.IN_PROGRESS]: 'In Progress',
        [TaskStatus.DONE]: 'Done',
        [TaskStatus.ARCHIVED]: 'Archived'
      };
      return labels[status];
    };

    const handleStatusChange = (newStatus: TaskStatus) => {
      if (props.onUpdate) {
        props.onUpdate({ ...props.task, status: newStatus });
      }
    };

    const handleDelete = () => {
      if (props.onDelete) {
        props.onDelete(props.task.id);
      }
    };

    return {
      getPriorityColor,
      getStatusLabel,
      handleStatusChange,
      handleDelete
    };
  },

  render() {
    const { task } = this;
    
    return (
      <div class={`task-card p-4 rounded-lg shadow ${this.getPriorityColor(task.priority)}`}>
        <div class="flex justify-between items-start">
          <h3 class="text-lg font-semibold">{task.title}</h3>
          <button
            onClick={this.handleDelete}
            class="text-red-500 hover:text-red-700"
          >
            Delete
          </button>
        </div>
        
        <p class="text-gray-600 mt-2">{task.description}</p>
        
        <div class="flex gap-2 mt-4">
          <span class="px-2 py-1 rounded text-sm">
            {this.getStatusLabel(task.status)}
          </span>
          <span class="px-2 py-1 rounded text-sm">
            {task.priority}
          </span>
        </div>

        {task.assignee && (
          <div class="mt-2 text-sm text-gray-500">
            Assigned to: {task.assignee}
          </div>
        )}

        {task.tags.length > 0 && (
          <div class="flex gap-1 mt-2">
            {task.tags.map(tag => (
              <span key={tag} class="px-2 py-1 bg-gray-200 rounded-full text-xs">
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }
});
