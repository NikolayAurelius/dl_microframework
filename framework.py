import numpy as np
from typing import AnyStr, Callable, Tuple, Dict, Union, List

import torch

eps = 1e-16


class Tensor:
    def __init__(self, value: np.array, requires_grad=False):
        self.value = value

        self.requires_grad = requires_grad
        if self.requires_grad:
            self.grad = np.empty_like(value)
            self.grad.fill(None)
        else:
            self.grad = None

    # def __mul__(self, other):
    #     if isinstance(other, Tensor):
    #         other = other.value
    #
    #     return Tensor(self.value * other, requires_grad=self.requires_grad)
    #
    # def __add__(self, other):
    #     if isinstance(other, Tensor):
    #         other = other.value
    #
    #     return Tensor(self.value + other, requires_grad=self.requires_grad)
    #
    # def __radd__(self, other):
    #     return self.__add__(other)
    #
    # def __rmul__(self, other):
    #     return self.__mul__(other)
    #
    # def __sub__(self, other):
    #     return self.__add__(-other)
    #
    # def __rsub__(self, other):
    #     return self.__sub__(other)
    #
    # def __truediv__(self, other):
    #     return Tensor(self.value / other, requires_grad=self.requires_grad)
    #
    # def __neg__(self):
    #     return Tensor(0 - self.value, requires_grad=self.requires_grad)


class Parameters(dict):
    # TODO: Как-то более грамотно стоит здесь выразить, что предполагается, что key экземпляры str,
    #  а item экземляры Tensor, float, int
    valid_key_types = (str,)
    valid_item_types = (Tensor,
                        float, np.float16, np.float32, np.float64,
                        int, np.int16, np.int32, np.int64)

    def __init__(self, *args, **kwargs):
        super(dict, self).__init__(*args, **kwargs)

    def __setitem__(self, key, item):
        if not isinstance(key, self.valid_key_types):
            raise ValueError(f'Parameters expects key is str instance, but your input is {key=} {type(key)=}')

        if not isinstance(item, self.valid_item_types):
            raise ValueError(
                f'Parameters expect item is instance of {self.valid_item_types}, but type of your input is {type(item)=}')

        super(Parameters, self).__setitem__(key, item)


class Operation:
    def __init__(self,
                 name: AnyStr,
                 f: Callable,
                 df: Callable,
                 params: Union[Parameters, None]):
        self.name = name
        self.f = f
        self.df = df
        self.params = params

        self.last_forward_result = None
        self.dfdx_adjusted_after_backward = None

        self.previous_nodes = []

        self.next_nodes = []

        self.input_size = None
        self.output_size = None

    # TODO: Может быть одновременно вычислять функцию и производную? Сделать режим трейн и инференс
    def compute_function(self, *args: Tuple[np.ndarray]) -> np.ndarray:
        return self.f(*args, params=self.params)

    def compute_derivatives(self, *args: Tuple[np.ndarray]) -> Dict[AnyStr, np.ndarray]:
        return self.df(*args, params=self.params)

    def set_shape(self, input_size: int, output_size: Union[int, None]):
        if self.input_size is not None or self.output_size is not None:
            raise PermissionError(
                f'Resetting shape is forbidden\nCurrent values: {self.name=} {self.input_size=} {self.output_size=}')

        self.input_size = input_size
        self.output_size = output_size

    def forward(self, *args: Union[np.ndarray, Tuple[np.ndarray]]) -> np.ndarray:  # -> Dict[AnyStr, Union[Tensor, Dict[AnyStr, Tensor]]]:
        # if not isinstance(args[0], Tensor):
        #     raise ValueError(f'*args must be Tensor or Tuple of Tensors {args=}')

        self.last_forward_result = {'f': self.compute_function(*args), 'df': self.compute_derivatives(*args)}
        # print(self.name, self.last_forward_result['f'].shape)

        assert all([self.input_size == arg.shape[1] for arg in args])

        assert len(self.last_forward_result['f'].shape) == 2, self.last_forward_result['f'].shape

        # TODO: Проверка shape параметров должна лежать на плечах forward наследника Layer
        # assert all([len(item.shape) == 3 for key, item in self.last_forward_result['df'].items()]), \
        #     f"Operation.name is {self.name} {dict([(key, item.shape) for key, item in self.last_forward_result['df'].items()])}"


        # assert len(self.last_forward_result['df']['dfdx'].shape) == 3, \
        #     f"Operation.name is {self.name} {dict([(key, item.shape) for key, item in self.last_forward_result['df'].items()])}"

        # assert self.last_forward_result['df']['dfdx'].shape == (args[0].shape[0], self.output_size, self.input_size), \
        #     f'dfdx shape must be (batch_size, output_size, input_size), ' \
        #     f'but yout input is {self.last_forward_result["df"]["dfdx"].shape=}\t' \
        #     f'{args[0].shape[0]=}'

        return self.last_forward_result['f']

    def backward(self):
        if len(self.previous_nodes) == 0:
            return


class Loss(Operation):
    def __init__(self,
                 name: AnyStr,
                 f: Callable[[Tensor, Parameters], Tensor],  # np.float64
                 df: Callable[[Tensor, Parameters], Tensor],  # np.float64
                 params: Union[Parameters, None]):
        super(Operation, self).__init__(name=name, f=f, df=df, params=params)

    def set_shape(self, input_size: int, output_size=None):
        super(Loss, self).set_shape(input_size, 1)

    def forward(self, *args: Union[np.ndarray, Tuple[np.ndarray]]) -> np.ndarray:
        y = super(Loss, self).forward(*args)
        assert len(y.shape) == 2 and y.shape[1] == 1 and all([y.shape[0] == x.shape[0] for x in args]), \
            f'{y.shape=}\t{[x.shape for x in args]}'
        return y

    def backward(self):
        super(Loss, self).backward()


class Activation(Operation):
    def __init__(self,
                 name: AnyStr,
                 f: Callable[[Tensor, Parameters], Tensor],
                 df: Callable[[Tensor, Parameters], Tensor],
                 params: Union[Parameters, None]):
        super(Operation, self).__init__(name=name, f=f, df=df, params=params)

    def set_shape(self, input_size: int, output_size=None):
        super(Activation, self).set_shape(input_size, input_size)

    def forward(self, x: np.ndarray) -> np.ndarray:
        y = super(Activation, self).forward(x)

        # new_shaped = np.empty((y.shape[0], y.shape[1], y.shape[1]))
        # for sample_num in range(y.shape[0]):
        #     new_shaped[sample_num] = np.diag(self.last_forward_result['df']['dfdx'][sample_num])
        #
        # self.last_forward_result['df']['dfdx'] = new_shaped
        assert y.shape == x.shape
        assert len(y.shape) == 2 and len(x.shape) == 2
        assert y.shape[1] == self.output_size and x.shape[1] == self.input_size
        return y

    def backward(self):
        super(Activation, self).backward()

        curr_forward = self.last_forward_result
        next_forward = self.next_nodes[0].last_forward_result

        next_dfdx = next_forward['df']['dfdx']

        if len(next_dfdx.shape) == 3:
            next_dfdx = np.sum(next_dfdx, axis=1)

        for sample_num in range(curr_forward['f'].shape[0]):
            for output_index in range(self.output_size):
                curr_forward['df']['dfdx'][sample_num, output_index] *= next_dfdx[sample_num, output_index]  # Здесь может быть и 3 измерения. Если дальше идет слой

        # for output_index in range(self.output_size):
        #     curr_forward['df']['dfdx'][:, output_index] = curr_forward['df']['dfdx'][:, output_index] * np.sum(next_forward['df']['dfdx'][:, output_index])


class Layer(Operation):
    def __init__(self,
                 name: AnyStr,
                 f: Callable[[Tensor, Parameters], Tensor],
                 df: Callable[[Tensor, Parameters], Tensor],
                 params: Parameters):
        super(Operation, self).__init__(name=name, f=f, df=df, params=params)

    def forward(self, *args: Union[np.ndarray, Tuple[np.ndarray]]) -> np.ndarray:
        y = super(Layer, self).forward(*args)

        assert all([y.shape[0] == x.shape[0] for x in args])
        return y

    def backward(self):
        super(Layer, self).backward()


class Dense(Layer):
    def __init__(self, input_size, output_size):
        dense_params = Parameters()
        dense_params['A'] = Tensor(np.random.random((output_size, input_size)), requires_grad=True)
        dense_params['b'] = Tensor(np.random.random(output_size), requires_grad=True)  # TODO: Может стоит задавать как (output_size, 1)

        f = lambda x, params: (np.matmul(params['A'].value[None, :, :], x[:, :, None]) + params['b'].value[:, None]).squeeze(-1)
        dfdx = lambda x, params: np.tile(params['A'].value, (x.shape[0], 1, 1))#np.matmul(params['A'].value[None, :, :], np.ones_like(x[:, :, None])).squeeze(-1)

        dfdA = lambda x, params: np.tile(np.expand_dims(x, axis=1), (1, params['A'].value.shape[0], 1))
        dfdb = lambda x, params: np.ones((x.shape[0], params['b'].value.shape[0]))

        df = lambda x, params: {'dfdx': dfdx(x, params), 'dfdA': dfdA(x, params), 'dfdb': dfdb(x, params)}

        super(Layer, self).__init__(name='Dense', f=f, df=df, params=dense_params)
        super(Layer, self).set_shape(input_size, output_size)

    def forward(self, x: np.ndarray) -> np.ndarray:
        y = super(Dense, self).forward(x)
        print('frwd dense', self.last_forward_result['df']['dfdx'].shape)

        assert len(self.last_forward_result['df']['dfdx'].shape) == 3, \
            f"Operation.name is {self.name} {dict([(key, item.shape) for key, item in self.last_forward_result['df'].items()])}"

        assert self.last_forward_result['df']['dfdx'].shape == (x.shape[0], self.output_size, self.input_size), \
            f'dfdx shape must be (batch_size, output_size, input_size), ' \
            f'but yout input is {self.last_forward_result["df"]["dfdx"].shape=}\t' \
            f'{x.shape[0]=}'

        assert len(x.shape) == 2 and len(y.shape) == 2
        assert x.shape[1] == self.input_size and y.shape[1] == self.output_size

        return y

    def backward(self):
        super(Dense, self).backward()

        curr_forward = self.last_forward_result
        next_forward = self.next_nodes[0].last_forward_result

        self.params['A'].grad = np.zeros_like(self.params['A'].grad)
        self.params['b'].grad = np.zeros_like(self.params['b'].grad)

        for sample_num in range(curr_forward['f'].shape[0]):
            for output_index in range(self.output_size):
                for input_index in range(self.input_size):
                    curr_forward['df']['dfdx'][sample_num, output_index, input_index] *= next_forward['df']['dfdx'][sample_num, output_index]

                    # Sum reduction hard coded
                    self.params['A'].grad[output_index, input_index] += next_forward['df']['dfdx'][sample_num, output_index] * curr_forward['df']['dfdA'][sample_num, output_index, input_index]
                    self.params['b'].grad[output_index] += next_forward['df']['dfdx'][sample_num, output_index] * curr_forward['df']['dfdb'][sample_num, output_index]



class Sigmoid(Activation):
    def __init__(self):
        # TODO: Сделать возможность вычислять производную через значения функции
        f = lambda x, params: 1 / (1 + np.exp(-x))
        dfdx = lambda x, params: f(x, params) * (1 - f(x, params))

        # def dfdx(x, params):
        #     print(x.shape, *x[:, 0])
        #     y = f(x, params)
        #     print(y.shape, *y[:, 0])
        #     y = y * (1 - y)
        #     print(y.shape, *y[:, 0])
        #     return y

        df = lambda x, params: {'dfdx': dfdx(x, params)}

        super(Activation, self).__init__(name='Sigmoid', f=f, df=df, params=None)


class BinaryCrossEntropy(Loss):
    def __init__(self, reduction='sum'):
        # TODO: Запилить другие reduction, не только сумму
        if reduction == 'sum':
            f = lambda pred, target, params: -(target * np.log(pred) + (1 - target) * np.log(1 - pred))
            dfdx = lambda pred, target, params: (pred - target) / (pred * (1 - pred))

            # def dfdx(pred, target, params):
            #     res = np.zeros_like(pred, dtype=np.float64)
            #
            #     for sample_num in range(pred.shape[0]):
            #         for output_index in range(pred.shape[1]):
            #             t = target[sample_num, output_index]
            #             p = pred[sample_num, output_index]
            #             print(t, p, 'tp')
            #             print(res[sample_num, output_index])
            #             res[sample_num, output_index] = (p - t)/((1 - p) * p)
            #
            #     return res

            df = lambda pred, target, params: {'dfdx': dfdx(pred, target, params)}
        else:
            raise ValueError(f'Unexpected value {reduction=}')

        bounding_pred = lambda pred: eps + pred * (1 - 2 * eps)

        bounded_f = lambda pred, target, params: f(bounding_pred(pred), target, params)
        bounded_df = lambda pred, target, params: df(bounding_pred(pred), target, params)

        super(Loss, self).__init__(name='BinaryCrossEntropy', f=bounded_f, df=bounded_df, params=None)
        # TODO: Добавить веса классов


class BatchNormalization(Layer):
    def __init__(self):
        raise NotImplementedError()


class Optimizer:
    pass


class Model:
    # TODO: Реализовать multiple inputs multiple outputs
    def __init__(self):
        raise NotImplementedError()


class Sequential(Model):
    def __init__(self, network_operations: List[Operation], loss_func: Loss):  # , optimizer: Optimizer):
        self.loss_func = loss_func
        self.network_operations = network_operations

        if not isinstance(self.network_operations[0], Layer):
            raise ValueError(f'First element in network_operations list must be instance of Layer or his child, '
                             f'but your input is {type(network_operations[0])=}')

        def create_graph():
            if not isinstance(self.network_operations[0], Layer) or self.network_operations[0].input_size is None or self.network_operations[0].output_size is None:
                raise ValueError(f'First operation must be Layer instance with given input_size, output_size')

            for k in range(len(self.network_operations) - 1):
                current_node = self.network_operations[k]
                next_node = self.network_operations[k + 1]

                if isinstance(next_node, Layer):
                    if next_node.input_size != current_node.output_size:
                        raise ValueError(f'Input size next operation must be equal output_size current operation, '
                                         f'but yout input is {next_node.input_size=} {current_node.output_size=}')
                else:
                    next_node.set_shape(input_size=current_node.output_size)
                    # TODO: Не нравится PyCharm'у мое отношение к сигнатурам в прошлой строке. Я неправ в чем-то?

            self.loss_func.set_shape(self.network_operations[-1].output_size)

            self.loss_func.previous_nodes.append(self.network_operations[-1])

            for k in reversed(range(1, len(self.network_operations))):
                previous_node = self.network_operations[k - 1]
                current_node = self.network_operations[k]

                self.network_operations[k].previous_nodes.append(previous_node)
                self.network_operations[k - 1].next_nodes.append(current_node)

            self.network_operations[-1].next_nodes.append(self.loss_func)

        create_graph()

        # for operation in [*self.network_operations, self.loss_func]:
        #     print(operation.name, operation.input_size, operation.output_size)

    def predict(self, X):
        pred = X
        for operation in self.network_operations:
            # print('check', isinstance(pred, np.ndarray), operation.name)
            pred = operation.forward(pred)

        return pred

    def forward(self, X, Y):
        return self.loss_func.forward(self.predict(X), Y)

    def backward(self):
        self.loss_func.backward()
        for curr_operation in reversed(self.network_operations):
            curr_operation.backward()

        # TODO: Reduction можно здесь сделать или нельзя, ведь grad у Tensor заданной размерности


# dense = Dense(10, 2)
#
# X = Tensor(np.random.random((3, 10)))
#
# pred = dense.forward(X)['df']
#
# print(pred.shape)
# print(pred)
# print(np.sum(pred, axis=0))
#
# import torch
#
# torch_A = torch.from_numpy(dense.params['A'].value)
# torch_A.requires_grad_()
# torch_X = torch.from_numpy(np.expand_dims(X.value, axis=2))
#
# f = torch.sum(torch.matmul(torch_A, torch_X))
# print(f.shape)
# f.backward()
#
# print(torch_A.grad.numpy())

np.random.seed(0)

model = Sequential([Dense(input_size=10, output_size=5), Sigmoid(), Dense(input_size=5, output_size=1), Sigmoid()],
                   BinaryCrossEntropy())

X = np.random.random((4, 10))
Y = 1 / (1 + np.exp(-np.sum(X, axis=1, keepdims=True)))

# print(model.forward(X, Y).shape)
#
# print(model.predict(X))
# print('forward', model.forward(X, Y))
model.forward(X, Y)

# for operation in model.network_operations:
#     if not isinstance(operation, Layer):
#         continue
#     print(operation.params['A'].grad)
#     print(operation.params['b'].grad)

model.backward()

# quit()
# print(model.network_operations[0].params['A'].grad)

torch_X = torch.from_numpy(X).cpu()
torch_Y = torch.from_numpy(Y).cpu()

print('Ошибка таргета', np.linalg.norm(Y - torch_Y.numpy()))


class Network(torch.nn.Module):
    def __init__(self):
        super().__init__()

        self.layer1 = torch.nn.Linear(10, 5)
        self.layer2 = torch.nn.Linear(5, 1)
        self.sigmoid = lambda x: 1 / (1 + torch.exp(-x))  # torch.nn.Sigmoid()

    def forward(self, x):
        return self.sigmoid(self.layer2(self.sigmoid(self.layer1(x))))


torch_model = Network().cpu()
with torch.no_grad():
    torch_model.layer1.weight = torch.nn.Parameter(torch.from_numpy(model.network_operations[0].params['A'].value))
    torch_model.layer1.bias = torch.nn.Parameter(torch.from_numpy(model.network_operations[0].params[
                                                                      'b'].value * 1))  # Если не умножать на ноль, то разницы нет, а если умножать, то появляется
    torch_model.layer2.weight = torch.nn.Parameter(torch.from_numpy(model.network_operations[2].params['A'].value))
    torch_model.layer2.bias = torch.nn.Parameter(torch.from_numpy(model.network_operations[2].params[
                                                                      'b'].value * 1))  # Если не умножать на ноль, то разницы нет, а если умножать, то появляется

pred = model.predict(X)
torch_pred = torch_model.forward(torch_X)
print(torch_pred.shape, torch_Y.shape, pred.shape, Y.shape)
torch_loss_func = lambda pred, target: -torch.sum(target[:, 0] * torch.log(eps + (1 - 2 * eps) * pred[:, 0]) + (1 - target[:, 0]) * torch.log(1 - eps - (1 - 2 * eps) * pred[:, 0]), axis=0)  # torch.nn.CrossEntropyLoss(reduction='sum')
torch_loss = torch_loss_func(torch_pred, torch_Y)
print(torch_loss.shape, torch_loss)
torch_loss.backward()

print('Ошибка предикта', np.linalg.norm(pred - torch_pred.detach().numpy()))
print('Ошибка лосса', np.abs(np.sum(model.forward(X, Y), axis=0).item() - torch_loss.item()))
print(np.sum(model.forward(X, Y)))

print('Ошибка градиента', np.linalg.norm(model.network_operations[2].params['A'].grad - torch_model.layer2.weight.grad.detach().numpy()))

# for operation in model.network_operations:
#     print([item.shape for key, item in operation.last_forward_result['df'].items()])

# При увеличении количества сэмплов торчевский градиент растет, а мой нет. Видимо где-то не суммируется
print(torch_model.layer2.weight.grad.detach().numpy())
print(model.network_operations[2].params['A'].grad)

print(torch_model.layer2.weight.grad.detach().numpy() / model.network_operations[2].params['A'].grad)
#
# for operation in model.network_operations:
#     print(operation.dfdx_adjusted_after_backward.shape)

torch_bce = lambda pred, target: -torch.sum(target[:, 0] * torch.log(eps + (1 - 2 * eps) * pred[:, 0]) + (1 - target[:, 0]) * torch.log(1 - eps - (1 - 2 * eps) * pred[:, 0]), axis=0)
torch_sigmoid = lambda x: 1 / (1 + torch.exp(-x))


class Input(Layer):
    def __init__(self, input_size, output_size):
        super(Layer, self).__init__(name='Input', f=lambda x, params: x, df=lambda x, params: {'dfdx': np.ones_like(x)}, params=None)
        super(Layer, self).set_shape(input_size, output_size)

def bce_test():
    print('\n\n\nBCE TEST\n\n\n')

    bce_model = Sequential([Input(1, 1)], BinaryCrossEntropy())
    torch_bce_model = lambda x, y: torch_bce(x, y)

    X = np.random.random((5, 1))
    Y = np.array(X > np.mean(X), dtype=np.int64)

    res = bce_model.forward(X, Y)
    print(bce_model.loss_func.last_forward_result)
    bce_model.backward()

    torch_X = torch.from_numpy(X)
    torch_X.requires_grad_()

    torch_Y = torch.from_numpy(Y)

    torch_res = torch_bce_model(torch_X, torch_Y)
    torch_res.backward()

    print('Ошибка лосса', np.sum(res) - torch_res.item(), np.sum(res), torch_res)
    print('Ошибка градиента', np.linalg.norm(torch_X.grad.detach().numpy() - bce_model.loss_func.last_forward_result['df']['dfdx']))

    print(torch_X.grad)
    print(bce_model.loss_func.last_forward_result['df']['dfdx'])


def sigmoid_test():
    print('\n\n\nSIGMOID TEST\n\n\n')

    sigmoid_model = Sequential([Input(1, 1), Sigmoid()], BinaryCrossEntropy())
    torch_sigmoid_model = lambda x, y: torch_bce(torch_sigmoid(x), y)

    X = np.random.random((5, 1))
    Y = 10 / (1 + np.exp(-np.sum(X, axis=1, keepdims=True))) + 0.5

    res = sigmoid_model.forward(X, Y)
    sigmoid_model.backward()

    torch_X = torch.from_numpy(X)
    torch_X.requires_grad_()

    torch_Y = torch.from_numpy(Y)

    torch_res = torch_sigmoid_model(torch_X, torch_Y)
    torch_res.backward()

    print('Ошибка лосса', np.sum(res) - torch_res, np.sum(res), torch_res)
    print('Ошибка градиента', np.linalg.norm(torch_X.grad.detach().numpy() - sigmoid_model.network_operations[1].last_forward_result['df']['dfdx']))

    print(torch_X.grad)
    print(sigmoid_model.network_operations[1].last_forward_result['df']['dfdx'])


sigmoid_test()

# bce_test()
